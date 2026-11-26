# Les décisions de Mika v2

Chaque décision d'architecture du moteur, en quelques lignes : ce qui a été décidé, et pourquoi. Le code et la
documentation les citent par leur numéro (« ADR 0050 ») : cherche ce numéro dans cette page. Les ADR complets
d'avant cette compilation (contexte, discussion, mesures, alternatives) restent dans l'historique git, sous
`backendv2/docs/adr/`.

**Lire une entrée.** Ses puces disent la décision au présent. « Révise » nomme les décisions qu'elle a changées ;
« Révisée par », celles qui l'ont changée après elle : la plus récente fait foi. Une décision « remplacée » ne vaut
plus que par ce qu'en garde son remplaçant.

**Ajouter une décision.** Une entrée au numéro suivant (un numéro ne sert jamais deux fois), dans la section de son
thème, sous la même forme : un titre `### NNNN — Titre`, cinq puces au plus, une phrase *Pourquoi*, la ligne
*Révise…* s'il y a lieu ; puis son numéro à la suite du « Révisée par » des entrées qu'elle change (une ligne
« Révisée par NNNN » si elles n'en ont pas : chacune ne le dit qu'une fois), et dans la carte. En cas de désaccord
avec le code, le code fait foi : corriger l'entrée, ou en ajouter une.

**Numéros non attribués :** 0167. Ce numéro a été sauté : aucune décision ne s'y est perdue, et il ne resservira pas.
`tests/architecture/test_docs_agree.py` lit cette ligne quand il vérifie la numérotation. Il vérifie aussi les
renvois : chaque « Révise » a son « Révisée par » (ou « Remplacée par ») dans l'entrée qu'il nomme, et l'inverse.

## La carte

| Thème | Décisions |
|---|---|
| Le noyau : journal, arbitrage, pipeline | 0001, 0002, 0003, 0006, 0007, 0008, 0009, 0014, 0015, 0021, 0040, 0059, 0149, 0151, 0221, 0222, 0223, 0306, 0311 |
| Le stockage | 0004, 0101, 0212 |
| Sa mémoire et ce qu'elle sait | 0010, 0011, 0034, 0046, 0052, 0055, 0074, 0076, 0078, 0079, 0080, 0081, 0082, 0083, 0084, 0085, 0086, 0087, 0091, 0099, 0109, 0110, 0111, 0153, 0224, 0263, 0264 |
| Identité et divulgation | 0012, 0035, 0075, 0092, 0133, 0134, 0148, 0184, 0185, 0186, 0188, 0207, 0220, 0226, 0298, 0303, 0304 |
| Sa vie intérieure : affect, corps, besoins, liens, initiatives | 0013, 0016, 0017, 0018, 0019, 0028, 0032, 0033, 0036, 0044, 0047, 0053, 0058, 0088, 0089, 0090, 0093, 0094, 0095, 0096, 0097, 0098, 0100, 0107, 0118, 0137, 0150, 0155, 0160, 0227, 0283 |
| Buts, projets, Forge et atelier | 0005, 0020, 0023, 0030, 0031, 0039, 0104, 0105, 0143, 0144, 0145, 0161, 0253, 0254, 0257, 0260, 0262, 0265, 0268, 0270, 0271, 0272, 0273, 0274, 0275, 0276, 0277, 0278, 0279, 0280, 0289, 0313 |
| Les sens et les plugins | 0022, 0027, 0037, 0038, 0061, 0063, 0064, 0066, 0068, 0069, 0106, 0117, 0119, 0120, 0128, 0129, 0130, 0131, 0132, 0147, 0163, 0166, 0168, 0171, 0172, 0189, 0190, 0191, 0192, 0193, 0194, 0195, 0196, 0198, 0199, 0211, 0213, 0214, 0228, 0229, 0236, 0238, 0240, 0243, 0244, 0245, 0246, 0247, 0248, 0249, 0250, 0251, 0255, 0256, 0258, 0259, 0269, 0299, 0300, 0301, 0302, 0305, 0307, 0309 |
| Les fournisseurs de modèles | 0026, 0072, 0073, 0127, 0136, 0142, 0157, 0158, 0239, 0267, 0285 |
| Sa voix, sa persona, la genèse | 0070, 0071, 0112, 0114, 0115, 0124, 0138, 0139, 0140, 0141, 0146, 0152, 0154, 0156, 0159, 0261 |
| Les clients, le fil, le monde | 0041, 0049, 0050, 0051, 0056, 0060, 0062, 0065, 0067, 0077, 0108, 0113, 0116, 0162, 0164, 0165, 0170, 0187, 0200, 0208, 0209, 0215, 0233, 0235, 0242, 0252, 0282, 0284, 0286, 0287, 0288, 0290, 0291, 0292, 0293, 0294, 0296, 0308, 0312 |
| La console et l'exploitation | 0024, 0025, 0029, 0042, 0045, 0057, 0103, 0121, 0122, 0123, 0125, 0126, 0169, 0173, 0174, 0175, 0176, 0177, 0178, 0179, 0180, 0181, 0182, 0183, 0197, 0201, 0202, 0203, 0204, 0205, 0206, 0210, 0216, 0217, 0218, 0219, 0225, 0230, 0231, 0232, 0234, 0237, 0241, 0281, 0295, 0297, 0310 |
| Ce que les sondes et les audits ont fixé | 0043, 0048, 0054, 0102, 0135, 0266, 0314 |

## Le noyau : journal, arbitrage, pipeline

### 0001 — Un journal d'événements, des réducteurs purs

- Tout changement d'état est un événement ajouté au journal ; rien d'autre n'écrit l'état.
- Chaque faculté possède une tranche immuable, déduite par des réducteurs purs et totaux, qui lisent les autres telles qu'elles étaient avant l'événement.
- Un événement porte des observations et des tirages enregistrés, jamais un état recalculé ; ses charges évoluent par upcasters.
- Le rejeu est exact (un instantané plus la queue égale le rejeu complet) : il fonde la simulation et l'explication causale ; une faculté ajoutée se reconstruit depuis la genèse.
- Le journal ne se réécrit jamais, sauf à l'oubli d'une clé `name:…`, remplacée par un jeton opaque dans les enveloppes (ADR 0073).

*Pourquoi :* un état dispersé dans des tables partagées et des singletons se perdait au redémarrage, sans moyen de rejouer ni d'expliquer.

*Révisée par 0073.*

### 0002 — Des faits typés et des contrats par propriétaire

- Les facultés ne s'importent jamais entre elles : elles se lisent par des faits typés.
- Chaque clé de fait a un seul fournisseur ; le graphe des lectures est acyclique, et toute lecture est déclarée.
- Une faculté ne réduit que les événements publics d'une autre, déclarés dans le contrat de leur propriétaire ; un événement est privé par défaut.
- Un type n'entre au vocabulaire partagé qu'avec au moins deux consommateurs, et en petites valeurs.

*Pourquoi :* en v1, 13 paquets sur 15 formaient un seul cycle d'imports, et l'intégration passait par le prompt et par des appels directs.

*Révisée par 0221.*

### 0003 — L'initiative par preuves cumulées et déclenchement à taux

- L'envie d'agir est un cumul de preuves en log-odds par (type d'épisode, cible), modulé par des décalages additifs ou des vetos.
- Le déclenchement est un processus de Poisson d'intensité `λ_max · σ(score)`, tiré par amincissement.
- Le comportement ne dépend jamais de la cadence d'évaluation.
- Les plages des preuves sont déclarées et leur atteignabilité vérifiée au démarrage ; la table des lignes explique chaque décision.

*Pourquoi :* le score linéaire de la v1, évalué toutes les 30 s, dépendait de la cadence et exigeait des plafonds qui somment exactement au seuil.

### 0006 — Le temps est injecté, le simulateur est une racine comme le serveur

- L'horloge, les identifiants et le hasard sont injectés, jamais lus directement.
- Le simulateur est une racine comme le serveur : une boucle asyncio à temps virtuel fait vivre le même noyau, déterministe, une semaine en moins d'une seconde.

*Pourquoi :* la v1 lisait six horloges et ne pouvait pas faire vivre l'agent entier sur une semaine : son comportement ne se jugeait qu'à l'usage.

### 0007 — Valider par des cibles d'intention, pas par parité avec la v1

- Chaque comportement se valide par une cible d'intention : ce qu'une personne ferait et pourquoi, une bande, et un contre-exemple qui doit échouer.
- Chaque bande est prouvée non vide par mutation.
- Les chiffres de la v1 donnent au plus un ordre de grandeur, jamais une assertion.
- Le contrat réseau se lit dans le code des clients, pas dans des trames enregistrées.
- Les politiques de produit (la divulgation graduée) et le contenu (la persona) se reprennent : ce sont des décisions, pas des mesures.

*Pourquoi :* les mesures de la v1 venaient de tests au temps simulé à la main, sans garantie que le système réel ait produit ces comportements.

### 0008 — Une décision se juge sur l'état où elle a été prise

- Une demande d'épisode née d'une sélection porte sa base de décision : l'état au moment du choix.
- La garde du départ compare l'état à cette base, pas à l'état au démarrage de l'épisode.
- L'arbitre ne choisit jamais une ligne dont l'épisode attend encore en file.
- Une initiative périmée pendant l'attente est supplantée, jamais livrée en retard ni choisie deux fois.

*Pourquoi :* une salutation en file derrière une réponse pouvait être choisie deux fois, puis partir après que la personne avait écrit.

### 0009 — Une question n'est réglée que par une réponse, ou un renoncement dit

- Seule une réponse, ou un renoncement journalisé, règle une question ; `interrupted`, `cancelled`, `superseded` et `preempted` ne la règlent pas.
- Une réponse supplantée ou préemptée est recomposée tout de suite, une réponse interrompue au démarrage, deux tentatives au plus ; au-delà de dix minutes, elle renonce et le journalise.
- Une panne scelle d'abord le magasin : rien ne s'écrit après l'instant de la panne.
- Une réponse qui échoue est dite à la personne, sans voix.
- Revu par l'ADR 0040 : la reprise vise le dernier message du tour, et l'échec se dit par la file de sortie.

*Pourquoi :* une panne ou un arrêt propre journalisait `cancelled`, ce qui retirait la question de l'attente et perdait le message.

*Révisée par 0040.*

### 0014 — Interprètes de perception ; salons ; Telegram

- Un interprète lit un message à son arrivée, sans modèle ; ses jugements sont journalisés avant la réponse, jamais recalculés au rejeu.
- En salon, elle entend tout mais ne répond qu'à ce qui lui parle (`addressed`) ; ce qui ne lui est pas adressé n'attend rien et ne compte pas comme un contact.
- En salon, l'historique est le fil du salon ; en privé, le fil de la personne, toutes ses adresses reliées si sa fiche est ouverte.
- Revu par l'ADR 0060 : le canal Telegram décidé ici est retiré.

*Pourquoi :* « moi c'est Alice » doit peser sur la réponse au message même, ce qu'un processus de fond ferait trop tard et qu'un réducteur ne peut pas faire.

*Révisée par 0038.*

### 0015 — L'arbitre tire contre une borne locale

- L'amincissement tire contre une borne locale (le double de l'intensité actuelle), jamais contre `λ_max`.
- L'intensité ne change qu'avec un événement (réévaluation immédiate) ou avec le temps (réévaluation périodique).
- Le tirage est indexé sur un compteur, jamais sur l'instant : il reste indépendant de la cadence des réveils.
- Ce qui évolue sur plusieurs jours, comme la guérison d'une ancre, se calcule en forme close.

*Pourquoi :* tirer contre la borne globale rejetait presque tout : deux jours simulés prenaient 14 s, contre 0,3 s.

### 0021 — Une écriture lancée va au bout ; la configuration précède la vie

- Une écriture lancée va au bout : une annulation reçue pendant l'écriture est retenue, l'ajout est publié, puis l'annulation rendue.
- Une écriture refusée (magasin scellé) lève sans rien publier.
- La configuration (persona, paramètres, fuseau) est journalisée avant que démarrent les voies, la reprise et les processus, au serveur comme au simulateur.

*Pourquoi :* une tâche annulée pendant la transaction laissait la racine non publiée ; l'ajout suivant reprenait les mêmes numéros et la file de sortie mourait.

*Révisée par 0040.*

### 0040 — Le tour de conversation, la parole qui n'attend pas, des boucles sûres

- Les messages sans réponse d'une adresse en un lieu forment son tour : une seule réponse, au dernier message ; un nouveau message supplante la réponse en cours.
- Une reprise répond une fois au dernier message du tour ; au-delà de dix minutes, le tour est abandonné en le disant. Un tour privé n'est jamais réglé en salon.
- La parole n'attend pas : elle fait céder un épisode moins prioritaire (`preempted`) et a sa file de sortie, à part des effets ; passé dix minutes, elle ne part pas.
- Jamais un artefact : au plafond de tours d'outils, un dernier tour sans outil lui demande de répondre ; une réponse impossible se dit sans voix, une fois par tour (`reply_failed`).
- Un épisode est toujours réglé, une seule fois. Un processus en échec ou stérile recule, une rafale est retenue ; une capacité non idempotente n'est jamais relancée après une panne.

*Pourquoi :* trois messages en rafale donnaient trois réponses, une réponse attendait derrière un `git push`, et un processus en échec écrivait des milliers d'événements.

*Révise 0009 (en partie), 0021 (en partie), 0036 (en partie).*

### 0059 — Tenir des années

- Ce qui grandit avec le temps se lit par index, jamais par parcours complet ni liste `IN (…)` : adresses par personne, moments par personne et par intervalle.
- La recherche vectorielle se filtre par personne, sous la même condition SQL : un échange de salon ne remonte jamais en privé.
- L'index des vecteurs suit la mémoire sans la relire ; la même mémoire répond pareil après un redémarrage.
- La file de sortie efface ses lignes faites après 30 jours ; ce qui n'est pas parti reste. Le dédoublonnage reste entier : une reprise peut redonner ses clés des mois plus tard.
- Ce qui a été oublié ne revient pas quand une projection se reconstruit.

*Pourquoi :* des parcours complets et des listes au-delà de la limite de SQLite l'auraient rendue lente, puis cassée, en quelques années.

*Révisée par 0135.*

### 0149 — Prendre la parole, se mettre au travail : deux réglages d'usage

- Deux paramètres du runtime (`RuntimeParams`), de −3 à +3 (0 par défaut), décalent le score de l'arbitre : « Prendre la parole » pour ses initiatives, « Se mettre au travail » pour ses pas, ses tâches et ses projets (`STEP`, `TASK`, `WORK`, `JOB`). Les réveils par API n'en ont pas : quelqu'un les attend.
- Le décalage est une modulation (`runtime.arbiter`, au nom de `runtime`) : chaque ligne le garde dans ses décalages, l'explication d'une décision le dit, « Voir l'effet » le montre avant qu'on l'enregistre ; à 0, il ne paraît pas.
- Loin du seuil, un point de plus la fait agir jusqu'à près de trois fois plus souvent pour les mêmes raisons (`σ(s + 1) ≈ e · σ(s)`) ; les seuils et les taux de la composition, et leur vérification au démarrage, ne changent pas.
- Ce n'est pas un trait : son caractère reste au tempérament, qui règle déjà ses preuves ; c'est un réglage d'usage (des heures calmes, une période chargée), sur la page « Moteur » des paramètres avancés.

*Pourquoi :* sa fréquence ne se réglait qu'en touchant une à une les preuves de chaque faculté, et les seuils de la composition étaient hors de la console (audit des garde-fous du 2026-10-27).

*Révisée par 0306.*

### 0151 — L'ordre du prompt est déclaré, pas déduit

- La composition déclare l'ordre de lecture de toutes les sections du prompt, une à une (`app/composition.py::READING`) : après sa persona, la zone stable ; l'historique ; puis son état interne — le moment, le monde autour d'elle, elle, ce qu'elle fait, ce qui est en cours avec la personne, la personne en face, vos souvenirs, ce qu'elle perçoit d'elle maintenant, ce qui la fait parler, les voix d'écriture, ce qu'on lui demande — et sa parole en dernier (« CE QUE TU TE RÉPÈTES », « TA RÉPONSE »). Chaque épisode n'en lit que les siennes, dans cet ordre.
- Le registre le vérifie : une section absente de l'ordre, inconnue ou redite y est une composition invalide. Sans ordre (une composition jouet), celui de la déclaration.
- Les ancres `after`/`before`, le tri topologique et les bandes du composeur (`background`, `interlocutor`, `LAST`) disparaissent ; « TA RÉPONSE » porte l'étiquette `chat`, que le mode pro coupe.
- Le prompt rendu garde le texte de chaque section par clé (`ChatPrompt.bodies`) : la seconde passe y lit qui est l'autre sans reparser le prompt par ses titres.

*Pourquoi :* aucune section ne portait d'étiquette de bande, et le tri départageait par la clé : l'état interne se lisait dans l'ordre alphabétique de ses clés anglaises — son journal d'hier (`yesterday`) en dernier, juste avant sa réponse, ce qu'elle perçoit de la personne séparé de qui elle est par onze sections de mémoire. Renommer une clé changeait son prompt (audit de la persona du 2026-10-28).

*Révise 0112 (en partie : `LAST`).*

### 0221 — Un type n'entre au vocabulaire partagé qu'avec trois propriétaires

- Un type n'entre au vocabulaire partagé (`vocab`) qu'avec au moins trois propriétaires, et en petites valeurs.
- Partagé par deux, il vit dans le contrat de son propriétaire (`contracts/`), que l'autre lit ; lu par un seul, il vit chez lui.
- Ce qui sort de `vocab` n'y laisse pas de réexport : chaque importeur suit.
- Ainsi le temps des choses (0084) : ses précisions sont des valeurs du contrat de la mémoire (`PRECISIONS`, `contracts/memory.py`), que la genèse lit aussi ; le reste n'a que la mémoire pour lecteur (`faculties/memory/timespan.py`). Rien ne change de ce qu'elle dit ni de ce qui est gardé au journal.

*Pourquoi :* ARCHITECTURE (« partagés par au moins trois propriétaires ») et l'ADR 0002 (« au moins deux consommateurs ») se contredisaient ; le code tenait déjà la règle de trois pour 19 modules sur 20, et les contrats par propriétaire, que pose la même ADR 0002, donnent sa place au cas de deux (audit du 2026-11-05 : K0-23, K1-05, décision K1-Q2).

*Révise 0002 (en partie : la règle d'entrée au vocabulaire partagé).*

### 0222 — Un port déclare ce qu'on lui demande

- Ce qu'un appelant lit d'un port, de la passerelle LLM ou du port d'entrée est déclaré dans son Protocol (`ports/`, `contracts/entry.py`), avec ses paramètres sous leur nom.
- Un membre que toutes les implémentations ont s'appelle directement. Un membre facultatif (une doublure du simulateur ou d'un test ne l'a pas) le dit dans sa docstring, et se lit par `getattr` sous son nom déclaré.
- Les quatre crochets que le runtime cherche sur chaque port (`open`, `shutdown`, `forget`, `failing`) sont écrits une fois, dans `ports/__init__.py`.
- `ports/` porte trois choses : ce que le cœur demande au dehors, les portes du transport web qu'`app` implémente (0213), et les bases SQL avec les aides pures qu'elles partagent.
- `tests/architecture/test_ports_declared.py` confronte chaque Protocol à ses implémentations (adaptateurs, portes d'`app`, doublures du simulateur et de l'aperçu) et chaque `getattr` sur un port à un membre déclaré, avec une liste blanche raisonnée : une excuse qui ne sert plus la fait échouer.

*Pourquoi :* la passerelle en service avait perdu `output_tokens` sans que rien ne casse, et chaque appel d'outil coupé se rejouait pour rien. Le transport web lisait par `getattr`, avec des replis morts, des méthodes que le port d'entrée ne déclarait pas (audit du 2026-11-05 : K2-01 à K2-03).

### 0223 — Un processus se réévalue à son propre quantum

- L'ordonnanceur garde l'échéance de chaque processus et ne la lui redemande qu'après un ajout au journal, après un passage de ce processus, ou à cette échéance, au plus tard à son quantum (`max_quantum_s`).
- Une échéance que le temps seul fait venir, sans événement (un fait `time_varying`, l'heure locale), se dit en instant absolu ; sinon le processus déclare le quantum qui borne son retard. Il ne compte jamais sur la cadence d'un autre : le rêve et la fin d'une nuit coupée, qui se lisent du sommeil de l'instant, ont leur quantum d'une minute.
- Une échéance relative (`frame.now + 15 min`) est un relevé à cette cadence, comptée depuis la dernière demande (un ajout la redemande) : gardée, elle arrive, au lieu de reculer à chaque passe ; plus longue que le quantum, elle n'arrive jamais.
- Seul l'ordonnanceur appelle `next_due` ; la console lit l'échéance qu'il a retenue (`Scheduler.due`).

*Pourquoi :* chaque passe recalculait les 55 échéances, et huit processus au quantum de 60 s en imposaient une par minute : sur S05, 35 910 passes et 35,7 s sur 45,5, et la voie rapide passée de 48 à ~85 s du 4 au 19 octobre sans commit coupable (audit du 2026-11-05 : LT, K3-01, K3-02).

*Révisée par 0227.*

### 0306 — « Préremplir » part tout de suite, et se suit en direct

- Ce qu'une personne lui demande et attend part **tout de suite** : « Préremplir avec Mika » dans Mail et dans Teams (frontendv2, l'application), « Lui demander une réponse » de la console, une réponse à reprendre. Sa tâche est une ligne **attendue** (`Candidate.awaited`), qui prend le taux des lignes attendues (`ArbitrationPolicy.awaited_rate` : une par seconde, au lieu d'une tâche toutes les cinq minutes en moyenne). Ni le décalage d'usage (0149) ni la retenue du quota (0127) ne la touchent.
- Elle part au **premier plan** (priorité 0) : une séance de travail en cours dans sa voie lui cède sa place (préemptée, l'arbitre la reproposera), et le fournisseur la sert avant le fond.
- **Même endormie** : le corps ne la retient pas (sommeil, réveil de nuit, inertie du matin) ; ce n'est pas une envie à elle, et on l'attend maintenant. Rien ne la réveille.
- Elle passe devant ce qu'elle fait d'elle-même sur la même ressource (sa tâche dans la même boîte, la même conversation) : supplantée, cette tâche ne compte pas d'essai (`vocab.episodes.gave_way`), pas plus qu'une séance préemptée dans la voie. Tant qu'une ressource est tenue par ce qui ne lui cède pas la place, elle attend sous un veto (`busy`) au lieu de perdre une occurrence par seconde ; la fin du bail la relance.
- Un essai qui a échoué (une panne, un délai) ou que la file a refusé attend une minute avant le suivant (veto `retry`) : une panne passagère ne brûle pas ses deux essais en deux secondes.
- On l'attend **une demi-heure** (`AWAITED_FOR_US`, le plafond des clients qui la suivent) : une demande bloquée plus longtemps redevient une tâche ordinaire, avec sa file et son sommeil.
- Ce qu'elle prépare **d'elle-même** ne change pas : la file, son tirage, son plafond du jour, son sommeil.
- **Où elle en est, en direct** : chaque épisode en cours tient son étape en mémoire (`EpisodeRunner.step_of` : elle réfléchit, ou tel outil tourne, son libellé, depuis quand), ni journal ni trace, comme l'activité du mode pro (0116). `/api/moi` la rend dans le fil Teams et dans un mail (`work` : `waiting` depuis la demande, `thinking`, `tool`). frontendv2 et l'application la montrent au-dessus de la saisie, sur une ligne : l'étape et son chrono, relus toutes les deux secondes.

*Pourquoi :* « préremplir avec Mika était extrêmement long » ; « tous les boutons préremplir doivent être live, l'utilisateur attend une réponse maintenant ; si elle décide de préparer un message, là, ça peut aller dans une file » ; « ça vaut aussi pour Android » (le 2026-11-22). La demande passait au tirage des tâches : en moyenne cinq minutes avant de commencer, plus quand elle était fatiguée, le matin quand elle dormait. Et l'écran ne disait que « elle s'y met ». Choisis le même jour : tout de suite même endormie, et une seule ligne.

*Révise 0016 (en partie : ce qu'on attend d'elle passe la porte de nuit), 0149 (en partie : « Se mettre au travail » ne décale plus ce qu'on attend d'elle), 0191 (en partie : « Préremplir » part tout de suite et se suit en direct).*

*Révisée par 0308.*

### 0311 — Un secret ne va ni au journal, ni à un prompt, ni à une trace

- **Un secret ne quitte son adaptateur que par une référence.** Un mot de passe, une clé, un jeton vit scellé dans les réglages ou dans la base de son domaine. Ce qui circule ailleurs — un événement, un fait, les paramètres d'un plugin, l'argument ou le résultat d'un outil, une section du prompt — n'en porte que le nom (une clé, un identifiant). Seul l'adaptateur qui s'en sert l'ouvre, au moment de s'en servir : le modèle ne voit jamais un secret et n'a jamais à en écrire un.
- **Ce qu'une action rapporte du dehors ne va pas en entier au journal.** L'aperçu d'une demande d'accord et le résultat d'une capacité (`contracts/runtime.py` : `EffectProposed`, `EffectExecuted.result`) sont du texte en clair, que l'oubli n'atteint pas. Une capacité qui lit le dehors — la sortie d'une commande sur une machine, le contenu d'un fichier distant — range ce qu'elle a lu à part, là où l'oubli et une purge l'atteignent, et ne rend au journal qu'un résumé borné et la référence de ce qu'elle a rangé.
- **Ce que les réglages donnent aux plugins ne porte jamais un champ scellé.** `inputs(settings)` (le câblage d'un domaine, `app/wiring.py`) est journalisé avec les paramètres : il dit à qui est un compte et s'il est coché, jamais son mot de passe. `tests/architecture/test_secrets_stay_out_of_the_journal.py` le garde, domaine par domaine.
- **Ce qui existe reste tel quel.** Les commandes réseau des projets (`projects.networked`) rendent déjà jusqu'à 3 000 caractères de sortie au journal ; elles ne manient aucun secret gardé. Elles suivront cette règle le jour où on y touchera ; un domaine neuf (un coffre de mots de passe, un bastion SSH) la suit d'emblée.

*Pourquoi :* le journal est sa vie, rejoué et sauvegardé tel quel : un secret qui y entre n'en sort plus. Rien ne le disait, et ce qui protège déjà — le masque des journaux du serveur, `Knob(secret=True)` dans les formulaires, `ToolResult.unkept` — ne couvre ni les paramètres journalisés ni les charges utiles des effets.

## Le stockage

### 0004 — Sans Django

- Le noyau n'a pas de framework : Starlette et uvicorn pour HTTP et WebSocket, Pydantic aux frontières.
- Un seul écrivain en base ; chaque projection appartient à sa faculté : la propriété des données est structurelle.
- L'authentification, les sessions et l'inspecteur sont propres à la v2.
- Revu par l'ADR 0101 : SQLAlchemy sur SQLite ou MariaDB remplace `sqlite3` en direct, toujours sans framework.

*Pourquoi :* l'ORM Django appelé depuis une boucle asyncio imposait 335 ponts `sync_to_async` et des lectures ORM partout.

*Révisée par 0101.*

### 0101 — Sa vie sur MariaDB : un schéma déclaré, deux moteurs

- SQLAlchemy 2.0 et Alembic : chaque table est une entité déclarée dans le paquet qui la possède ; l'ORM pour les entités, le style requête pour le journal et les projections. Ni Django, ni ORM asynchrone.
- MariaDB en service, sur la machine de Mika par socket Unix (`MIKA_DATABASE_URL`, `MIKA_DATABASE_PREFIX`), serveur dédié ; SQLite pour les tests, le simulateur et le jumeau. Un seul code.
- Aucun SQL propre à SQLite : ce qui diffère passe par des aides compilées par moteur (`upsert`, `insert_ignore`…) ; le chemin chaud est préparé (`Prepared`).
- `BIGINT` pour instants et `seq`, `Key(n)` bornée à l'écriture pour toute clé indexée, `LONGTEXT` sinon ; collation `utf8mb4_nopad_bin`, recherche sur un texte replié.
- Alembic pour les tables stables : chaque base passe à `head` avant toute ouverture, sinon pas de démarrage. Une projection évolue par sa version et une reconstruction.
- Une base et un compte par app de la Forge, droits sur sa seule base (ni `EVENT`, ni déclencheur, ni `GRANT`), 100 Mo ; l'app passe par l'hôte (`api.query`, `api.execute`), jamais par les bases de Mika.
- Oubli : binlog coupé, place libérée remise à zéro ; un texte oublié quitte les tables tout de suite, les journaux d'InnoDB sous peu.
- Sauvegarde : un `mariadb-dump` par base à côté du dossier de données, vérifié par rejeu, sans `mika_views` ; une archive de fichiers ne se restaure pas sur un serveur, ni l'inverse.

*Pourquoi :* sa propriétaire voulait sa vie dans MariaDB, où le SQL écrit pour SQLite cassait ou se trompait sans erreur.

*Révise 0004 (en partie), 0023 (en partie), 0024 (en partie), 0073 (en partie). Révisée par 0135.*

### 0212 — Un seul repli du texte, et une clé de nom qui ne bouge pas

- Comparer deux textes passe par `kernel/text.py::fold` : ni casse ni accents, les ligatures dépliées (« sœur » → « soeur »), `ß` en `ss`. `ports.paging.fold_text`, `vocab.words.fold`, la clé d'émotion `vocab.affect.emotion_key` (bâtie sur lui), le composeur et les filtres de l'inspecteur s'y ramènent.
- Ce qui est écrit replié change avec lui. Les colonnes de `mail`, `teams` et `feeds` passent par une révision qui déplie leurs ligatures en SQL (`unfold_ligatures`), sans relire les textes ; `thread` (version 10) et `memory_items` (version 21) se reconstruisent depuis le journal. La révision ne déplie que les ligatures : une ligne d'avant garde les majuscules de ses signes de compatibilité (« ™ » y reste `TM`), et ne se retrouve plus en tapant ce signe ; un mot tapé en ASCII ne la trouvait pas non plus avant.
- `vocab.people.fold` reste à part : elle forme les clés `name:…`, écrites au journal, et `name_aliases` les recalcule pour l'oubli. Sa casse reste `lower` et ses ligatures restent : « Lætitia » garde `name:lætitia`, sinon une mention déjà écrite ne serait plus reliée à la personne, ni oubliée avec elle. `same_name` et `mentions`, qui ne forment aucune clé, suivent le repli commun. `same_name` décide pourtant dans deux réducteurs d'`identity` (une revendication, un démenti) : « Lætitia » et « Laetitia » y deviennent un seul nom, et la tranche passe en version 8 pour se reconstruire depuis la genèse, sinon un instantané d'avant et un rejeu complet ne donneraient pas le même état.
- La table des pièces reçues garde les lettres de ce qu'elle a déjà, le `ß` et quelques signes hors du français : une pièce d'avant cette décision ne se retrouve pas par un mot qui en contient un. Elle n'a jamais été reconstruite, et le français n'a pas ces lettres : elle ne l'est pas pour elles.

*Pourquoi :* l'audit du 2026-11-05 a trouvé le repli recopié dix-neuf fois, une seule copie dépliant les ligatures : la recherche de la console ne trouvait pas « sœur » pour « soeur », alors que le rappel de sa mémoire le faisait. Changer `fold_text` sans réécrire ce qui était gardé aurait perdu « sœur » même tapé tel quel, et replier les clés de nom comme le reste aurait coupé l'oubli des mentions déjà écrites.

## Sa mémoire et ce qu'elle sait

### 0010 — La mémoire : trois étages, un oubli qui se calcule, un index qui n'est qu'un cache

- Trois étages : le fil verbatim ; des extraits d'échanges par personne, sans modèle ; ce que la consolidation garde, en événements (`memory.remembered`, `memory.believed`).
- Chaque élément porte un texte effaçable, sa provenance, sa sensibilité et son importance ; la consolidation ne coupe jamais une paire question-réponse.
- L'oubli ne balaie rien : le poids se calcule à la lecture, d'une demi-vie qui croît avec l'importance et les rappels ; sous un seuil, le souvenir dort, mais `memory_search` le trouve.
- Le rappel mêle pertinence, poids, lien à la personne, humeur bornée et anti-répétition ; la divulgation le filtre, et le composeur garde une seconde barrière.
- L'index de vecteurs n'est qu'un cache : oublié avec la personne, reconstructible depuis le journal.

*Pourquoi :* garder l'important, laisser le reste s'estomper sans le perdre, ne pas répéter une confidence à n'importe qui, et rester rejouable.

*Révisée par 0034.*

### 0011 — Ce que le premier test réel a changé : dans le doute, on ferme

- Dans le doute, on ferme : un élément consolidé qui ne nomme personne concerne toutes les personnes de la conversation.
- La chaleur d'une relation se mesure au-dessus du repos commun, jamais sur la valeur absolue de l'ancre.
- La santé, le travail, l'argent, la famille, les amours et les émotions de quelqu'un sont au moins « personnels ».
- Elle sait quel jour on est : la date entre au prompt.

*Pourquoi :* sur un vrai modèle, une liste de personnes omise rendait une confidence dicible à tous, et tout le monde paraissait « chaleureux » d'emblée.

### 0034 — La mémoire sait qui le lui a dit

- La consolidation relit une conversation par appel (un fil privé, ou un salon d'un seul tenant) ; un nom qu'elle ne résout pas sans ambiguïté reste `name:…`.
- Chaque élément porte `told_by` (qui l'a dit) et `heard_by` (qui était là) : ce que Bob dit d'Alice n'est pas « à Alice ». Le profil ne se nourrit que de première main.
- Un secret ne ressort que devant qui l'a confié, et ce qui le laisse deviner devient secret ; une confidence peut s'ouvrir à une proche, étiquetée « X te l'a confié ».
- Elle sait qu'elle sait : une ligne vague, sans contenu, jamais devant la personne concernée ni en public.
- Une croyance ne monte en confiance que par un nouvel informateur ; seul ce qu'elle a repris en parlant renforce un souvenir. L'oubli d'une personne efface ce qu'elle a confié.

*Pourquoi :* consolider une fenêtre entière d'un seul appel faisait d'un tiers le témoin d'un secret, et servait à Alice ce que Bob avait dit d'elle.

*Révise 0010 (en partie). Révisée par 0043.*

### 0046 — La vie des autres, sa parole, et ce qui tient

- Un moment de leur vie est « repris » quand on en parle, pas quand il est passé sous ses yeux. La veille elle encourage (`others.cheer`), après elle demande (`others.follow_up`), une fois.
- Une promesse datée se tient au moment dit (`memory.keep_promise`, dans `agency.OWED`) ; une promesse sans date ne déclenche rien.
- Une conversation close (« bonne nuit ») n'attend pas de réponse. Le délai attendu court sur les heures où la personne écrit (`others.hours`).
- Ce qu'elle dit d'elle (goût, avis, fait de sa vie) tient ; changer d'avis remplace l'ancienne croyance. Le ton suit le lien : une inconnue n'est pas taquinée.
- Ce qu'elle a vécu avec qui elle aime dure plus. Avoir été dure avec une amie laisse un remords, jamais envers une inconnue.

*Pourquoi :* elle oubliait ce qu'elle avait seulement vu passer, ne tenait pas parole à l'heure et parlait à une proche comme à une inconnue.

*Révisée par 0048, 0052.*

### 0052 — Promesses, rappels et moments de leur vie

- Une promesse datée ne se tient pas avant son jour ; « abandonnée » passe toujours. Un jour sans heure est dû toute la journée.
- Un rappel demandé existe une fois : accepté en mots, c'est une promesse ; une promesse qui double un rappel programmé (même personne, même chose, même jour) n'est pas notée. Le code tranche, pas le modèle.
- Une chose à faire (« prendre rendez-vous ») est une promesse, pas un moment de sa vie.
- Quand un deuil, une rupture ou une maladie touche la personne (`memory.hard_times`), le banal se tait et ses nouvelles passent d'abord.
- Ce qui se fête se souhaite le jour même (`others.celebrate`), une fois, sans réponse attendue ; jamais la date d'un deuil.

*Pourquoi :* une promesse se tenait la veille, un rappel n'existait que si le modèle appelait l'outil, un suivi banal tombait au lendemain d'un deuil.

*Révise 0046 (en partie). Révisée par 0054, 0084.*

### 0055 — Ce qu'elle retient d'une conversation

- Une réplique recopiée n'est pas un souvenir. La sienne n'est jamais gardée ; celle de la personne devient « Sam m'a dit : « … » », confiée par son auteur, si elle compte.
- Une banalité ne se garde pas (partir, aller dormir, se dire au revoir) ; un même moment ne se note qu'une fois.
- Ce qui n'appartient qu'à eux (`entre_vous` : son surnom, leurs blagues) est de première main, jamais dit devant une inconnue ni en public.
- Une fiche n'invente pas : couple, enfants, travail ou âge viennent de ses matériaux ; ses intérêts sont des goûts.
- « Oublie ce que je t'ai dit sur X », en conversation, est une révision, pas un oubli : l'effacement passe par la console.

*Pourquoi :* avec un modèle d'extraction faible, elle gardait ses répliques et des banalités, oubliait son surnom, et sa fiche inventait.

*Révise 0048 (en partie), 0054 (en partie). Révisée par 0153.*

### 0074 — Ce qu'elle sait, de qui, et devant qui

- Un secret ne sort jamais dans une audience publique, même devant qui l'a confié ; ce refus passe avant toute exemption.
- Un lien du graphe social suit la croyance d'où il vient : devenue secrète, il devient secret et n'ouvre pas le niveau « lié » ; remplacée, il quitte l'archive.
- Une situation finie n'est jamais candidate au « déjà noté » ; à une autre date, un moment n'en remplace un autre que si tous les mots de l'un sont dans l'autre (mieux vaut un doublon qu'une perte).
- Une note sur elle ne suit sa mémoire de soi que si elle vient de sa bouche ; ce qu'un autre dit d'elle suit le chemin commun, confident et secret compris.
- Ce qui ne peut pas se dire n'étouffe pas le rappel : l'écart au meilleur candidat se mesure parmi ce qui peut se dire ici, et `memory_search` élargit sa recherche tant qu'il en manque.

*Pourquoi :* un audit voyait des secrets recopiés en salon, des liens survivant à leur croyance et un rappel étouffé.

*Révisée par 0075, 0076, 0078, 0079, 0080, 0081, 0082.*

### 0076 — Ce qu'elle déplace, ce qu'elle a vécu, ce qu'elle tait, ses mensonges

- Un moment déplacé remplace celui que la relecture désigne parmi les moments montrés, et en hérite secret, sensibilité et poids. Un report repousse la date.
- Elle tait avec jugement : jamais un refus de répondre, qui avoue un secret ; elle donne son avis sur ce qui se voit, retourne la question ou renvoie à la personne.
- Un souvenir à la première personne est toujours le sien ; un « je » qui reprend 60 % des mots d'un autre devient ce que cette personne lui a dit.
- Elle peut mentir, et ça lui pèse : `[MENSONGE: …]` ne part jamais ; une gêne et un souvenir étiqueté (`memory.lies`), secrets, ne ressortent que devant la personne trompée, en privé.
- La CLI reçoit l'effort de réflexion du fournisseur ; le modèle de plongements se charge au démarrage, en fond.

*Pourquoi :* une sonde montrait un report qui trahissait un secret, des refus de robot et des souvenirs écrits à la place des autres.

*Révise 0074 (en partie).*

### 0078 — Une seule porte vers ce qu'elle sait

- Le verdict de divulgation (`admissible`) vit dans `vocab.privacy`, applicable par toute faculté, avec les audiences planchers `private_to(personne)`, `PUBLIC_FLOOR` et `INTERNAL`.
- Un texte porte sa filiation : chaque source apporte une exigence, toutes doivent tenir (`vocab.lineage.admits`). Une filiation absente n'est jamais vide : le lecteur garde son ancienne règle.
- Hors de la mémoire, ce qu'elle sait ne se lit que par les vues de `contracts.memory` (`KNOWLEDGE_VIEW`…), jamais en SQL brut ; `LEDGER_VIEW` et `FORMER_VIEW` sont interdits aux facultés et plugins.
- Un texte écrit pour une audience est filtré au plancher de qui le verra (portrait, réflexion sur quelqu'un, récit de soi) ; un texte écrit pour elle (rêve, pensée, journal) garde sa filiation et se juge à l'affichage.
- La pensée d'une révision exige ce que permettent l'ancienne et la nouvelle croyance.

*Pourquoi :* une douzaine de lecteurs filtraient chacun à sa façon, et un secret revenait par un rêve, une pensée ou un récit.

*Révise 0074 (en partie). Révisée par 0082.*

### 0079 — Les fils des moments

- Un moment a un fil (`LifeEvent.thread`), le premier numéro qui l'a noté : redit, reporté ou rouvert, il le garde. `memory.MOMENT_THREAD` rend le fil d'après n'importe lequel de ses numéros.
- Un suivi porte son fil et l'occurrence reprise : sous un numéro remplacé, il vise le moment tel qu'il est noté, s'il est à la même date.
- Une situation finie depuis moins de `memory.recurrence_days` (60 j) qui revient se rouvre (`recurs`) et en hérite secret, sensibilité et poids ; au-delà, c'est une autre histoire.
- Ce qu'elle en dit se range sous le fil : l'encouragement de la veille se dit une fois par date, et une matière tirée d'un moment reporté ne resert pas.

*Pourquoi :* chaque notation donnait au moment une autre identité : ce qu'elle en avait dit se perdait ou se répétait.

*Révise 0074 (en partie).*

### 0080 — Une proposition, des témoignages

- Une croyance est une proposition (texte, personnes, nature, porteur) et ses témoignages (`memory_testimonies`) : qui l'a dit, de qui il le tient, qui l'a entendu, secret, sensibilité, confiance.
- La même proposition, quel qu'en soit le témoin, reçoit un témoignage (`memory.attested`), jamais une seconde ligne ; la même personne qui redit de même source n'ajoute rien.
- La confiance se met en commun sur des témoins distincts, bornée à 0,95 ; au rappel, sur les seuls témoignages que l'audience peut entendre.
- Elle dit une croyance là où un témoignage le permet, en ne nommant que ce témoin ; la ligne garde l'enveloppe la plus stricte pour les autres facultés.
- La discrétion de la personne concernée ferme tous les témoignages, ceux d'après compris ; celle d'un autre ne ferme que le sien. Les souvenirs nés des mêmes messages se ferment avec.
- Oublier un témoin efface son témoignage ; oublier le premier emporte la proposition. La nuit réunit les doublons (`memory.joined`).

*Pourquoi :* une même chose dite par deux témoins faisait deux lignes, et l'une ou l'autre décidait au hasard du rappel.

*Révise 0074 (en partie).*

### 0081 — Le vrai, le contesté, le révolu

- Qui a raison ne dépend pas de qui l'a entendu. Sûreté d'un témoin : 3 elle-même ou la personne concernée, 2 vu ou de première main, 1 rapporté, 0 déduit.
- Le même témoin qui se corrige remplace ; une source de première main au moins aussi sûre remplace ; sinon elle conteste, et les deux restent vivantes. Deux avis de deux porteurs ne se corrigent pas.
- Ce qui est remplacé sait par quoi (`superseded_by`) ; une croyance remplacée, redite, revient si elle gagne contre l'actuelle.
- Une croyance porte depuis quand et jusqu'à quand elle est vraie ; révolue, elle ne revient pas d'elle-même.
- Le doute se dit en attribuant l'autre version à son témoin, seulement si les deux peuvent se dire ici. Changer d'avis sur ce qui la définit se ressent.

*Pourquoi :* la vérité se jugeait avec l'audience : la personne concernée ne corrigeait pas un ragot, et un ragot pouvait gagner.

*Révise 0074 (en partie).*

### 0082 — Ce qui en dérive

- Ce qu'un événement de la mémoire retire (devenu secret, remplacé, contesté, joint, situation finie) se définit une fois (`contracts.memory.withdrawals`), sans événement de plus.
- Un secret fait taire tout de suite ce qui en dérive : la pensée s'oublie, le rêve ne se raconte pas, le journal ne montre que sa version partageable, récit et portrait se taisent jusqu'à leur réécriture.
- Une source remplacée ou contestée rend récit et portrait périmés : ils se réécrivent sans recevoir le texte d'avant, et gardent leurs sources.
- Un rêve, une journée écrite restent ce qu'ils étaient : seulement tus devant un secret.
- Un résumé de salon dit qui parlait (l'oubli d'un participant l'efface) et tait les messages d'où vient un secret ; un secret déclaré après coup le fait refaire (`transcript.summary_reset`).

*Pourquoi :* un texte dérivé gardait ce que sa source avait depuis rendu secret, remplacé ou contesté.

*Révise 0074 (en partie), 0078 (en partie).*

### 0083 — Ce que chacun en ressent

- La relecture juge deux ressentis pour chaque souvenir, croyance ou moment : celui de la personne (`felt`) et le sien (`empathy`), en facettes de 0 à 1 parmi les 29 émotions, trois au plus.
- Une émotion est jugée par le modèle, jamais devinée par un lexique ; une forme illisible ne fait jamais perdre l'élément.
- Chaque élément est relié à ses émotions (`memory_feelings`) : `memory_search` cherche par `ressenti` et `de_qui`, à la demande du modèle.
- Devant une proche, une confidence tue se dit selon ce que vit la personne : une peine « un moment difficile », une joie « une bonne nouvelle, pas encore à annoncer », l'inconnu « quelque chose qui lui tient à cœur ».
- Le rappel dit les ressentis en mots, jamais en nombre ; les temps durs pèsent toutes les facettes.

*Pourquoi :* toute confidence tue se disait « un moment difficile », et rien ne disait ce que chacun ressentait.

### 0084 — Le temps des choses

- Une date garde sa précision (`faculties.memory.timespan`) : jour, mois, saison, année ou période, dite comme on la dit. Une période n'a ni veille ni lendemain : ni encouragement, ni suivi, ni vœux.
- Le monde n'est la vie de personne (portée `world`, oublié avec qui l'a dit). Elle n'a pas de corps : elle vit à travers quelqu'un (`shared`), jamais un moment inventé à elle.
- Le fait `memory.ahead` et « CE QUI VIENT » montrent le monde et les moments partagés à venir, au verdict de chaque moment.
- La vraisemblance a un a priori par nature (0,9 de première main, 0,7 rapporté, 0,98 officiel, 0,6 prévision) que ce qu'on en dit ne peut qu'abaisser ; dite en mots, jamais en nombre.
- Une prévision est une croyance `prediction`, à qui la porte ; passée sa période, elle ne revient pas d'elle-même.

*Pourquoi :* un moment n'avait qu'un jour, le monde se rangeait dans la vie de qui en parlait, et aucune prévision ne se gardait.

*Révise 0052 (en partie). Révisée par 0099, 0153.*

### 0085 — Ce qu'elle lit devient ce qu'elle sait

- Une lecture naît de `rss.read` ou de `mcp.consulted` (pendant un travail seulement, jamais en conversation, sur un serveur réglé `learns`, décoché par défaut) ; elle attend la nuit.
- La relecture de nuit (`memory.reread`) fait un appel au plus. Une croyance lue a la source pour témoin, origine `read` (0,7 au plus), anodine, sans personne ; ses contradictions se jugent comme en ADR 0081.
- Ses avis à elle, sur tout, politique comprise, naissent aussi de ses lectures (deux par nuit au plus) et la définissent.
- La nuit confronte deux témoins : la même chose se joint muette (pour la confiance, jamais pour ce qui peut se dire) ; une contradiction se tranche ou fait douter. Un secret ne se blanchit jamais en « lu ».
- Ce qu'elle a lu se dit quand elle prend la parole ou qu'on s'adresse à elle, une fois par personne. « LES GENS QU'ON NOMME » lui dit qu'elle connaît quelqu'un de ce nom, sans rien en dire.

*Pourquoi :* ce qu'elle lisait seule ne devenait jamais un savoir, et deux témoins aux mots différents ne se rencontraient jamais.

*Révisée par 0110, 0127, 0128, 0153.*

### 0086 — Voir venir, constater

- L'issue d'un moment (`memory.resolved` : `happened`, `cancelled`, `moved`, `unknown`) se tranche une fois pour toutes, avec l'attente et la surprise ; tranchée, elle ne se redemande jamais.
- Seule la personne concernée constate, de ses mots (un autre ne fait qu'une rumeur) ; une lecture constate un moment du monde si elle en parle ; sans nouvelles après 21 j : `unknown`, ni surprise ni leçon.
- Elle apprend de qui annonce (reports, annulations) et de ses attentes (score de Brier) : les annonces valent moins, ses mots se font prudents. Le chiffre ne se dit jamais.
- L'issue se ressent (surprise, attente déçue, crainte levée) ; le moment qui domine se fait attendre une fois par jour (`attention.anticipated`). Un moment partagé qui a eu lieu devient un souvenir à elle.
- Un moment du monde qui lui tient à cœur se vérifie (`memory.to_check`), deux fois par semaine au plus. Un dépassement du plafond de sortie de la CLI est une réponse tronquée, pas une panne.

*Pourquoi :* rien ne gardait comment un moment avait tourné : elle redemandait l'annulé et n'apprenait rien.

### 0087 — Ce qu'elle dit d'elle-même tient

- Une seule table des genres : goûts et préférences sont des `preference` qui la définissent et tiennent des mois ; un avis une `opinion` ; un fait de sa vie un `claim` qui tient ; une anecdote s'efface.
- Les mêmes mots sont la même note : redite comme ce qui la définit, une anecdote le devient, jamais l'inverse. Revenir à son ancien avis le ramène : sa parole sur elle-même tranche.
- Jamais une note sur elle, ni un pronostic à elle, né d'un mensonge, même sans citation dans une conversation où elle a menti.
- Un moment vécu à travers quelqu'un garde un « en bref » (`gist`) sans nom, chiffre ni date, jamais d'un moment secret ni d'une confidence.
- L'ordre des imports de `self` fixe l'ordre de ses sections dans le prompt : il est épinglé.

*Pourquoi :* ce qu'elle disait d'elle s'effaçait comme une anecdote ou se contredisait.

*Révisée par 0264.*

### 0091 — Raconter sans nommer

- À qui n'a aucun lien connu avec la personne, elle peut raconter sans nommer : une version sans nom (`veiled`) écrite par la relecture, sous un filet du code (aucun nom connu, aucun chiffre, bornée).
- Jamais pour un secret, ce qui n'appartient qu'à deux, un avis, un mensonge, une mention présumée, la vie de sa propriétaire, un événement marquant ; jamais à qui est concerné.
- Gradué selon qui écoute (`veiled_level`) : l'anodin en salon ou devant qui elle connaît mal, le personnel devant une connaissance, une confidence devant une amie sûre.
- Un lien qui ouvre doit être prouvé, un lien qui ferme seulement soupçonné ; un nom inconnu ou une panne ferment. Ce qui se dit nommé se dit nommé ; raconté sans nom, ça le reste.
- En réponse seulement (ni initiative, ni journal, ni récit), jamais une preuve d'identité. Un bloc sans nom tombe si un nom qu'il tait paraît ailleurs dans le prompt.

*Pourquoi :* elle se taisait, ou trahissait un secret, là où une humaine raconterait sans nommer.

*Révisée par 0092, 0099.*

### 0099 — La mémoire tient sa porte : sujets délicats, jours nommés, prévisions constatées, mémoire prête

- Ce qui touche un sujet délicat d'une personne (mêmes radicaux que le rappel) devient une confidence dans la mémoire même (`memory.delicate`), pour toutes les facultés ; jamais abaissé ensuite.
- La relecture voit chaque jour nommé et daté, de la semaine d'avant aux deux semaines qui viennent : un « lundi » se situe sans calcul.
- Le serveur attend le modèle de plongements avant de la faire vivre, 30 s au plus ; au-delà, elle vit sans.
- Une prévision échue se montre à la relecture ; constatée par une personne qu'elle concerne, elle devient `memory.resolved` et nourrit la fiabilité de qui l'a prévue et sa calibration. Une rumeur ne constate rien.
- En réponse, une recherche à part parmi les éléments qui ont une version sans nom ; jamais en salon ni en initiative.

*Pourquoi :* le délicat n'était confidentiel que pour le rappel, et une prévision ne se vérifiait jamais.

*Révise 0084 (en partie), 0091 (en partie).*

### 0109 — Un modèle de plongements pour le français, choisi par la machine

- Une requête n'est pas un document (`embed_query`) : chaque texte reçoit la consigne que son modèle attend ; pour Qwen3-Embedding, la consigne de souvenirs de `voix.yaml`.
- Le modèle et l'appareil se choisissent par machine : `MIKA_EMBEDDINGS_MODEL` et `MIKA_EMBEDDINGS_DEVICE` (`cpu`, `cuda`, `auto`) ; serveur et CLI passent par le même choix.
- L'index range ses vecteurs par modèle : changer de modèle se replonge seul.
- La précision dépend du modèle : fp16 seulement pour une famille qui le supporte ; jamais pour EmbeddingGemma 2, qui y rend des NaN sans erreur.
- Le portable fait tourner EmbeddingGemma 2 sur sa GTX 1650 : la qualité de Qwen3-0.6B, cinq fois plus vite, pour moitié moins de mémoire.

*Pourquoi :* l'ancien MiniLM, écrit en dur, servait mal le français et plongeait une requête comme un document.

*Révisée par 0111.*

### 0110 — Le monde dans sa mémoire : une seule base

- Le monde lu partage l'index de ses souvenirs : à 4 666 faits du monde, elle retrouve ses proches aussi bien que sans, et une base à part perdrait un tiers de ce qu'elle sait du monde.
- Une personnalité publique n'est pas une personne de sa vie : des faits lus, sans personne créée, ni profil, ni lien.
- Ce qu'elle lit pour quelqu'un en conversation (`mcp.consulted`, `rss.read`) porte `asked_by` ; la nuit n'en garde que les nouvelles et les faits publics, jamais ce que la personne cherchait.
- Ce qu'elle en garde est du monde, entendu par qui l'avait demandé, qui ne se le voit pas resservir comme une nouvelle ; les arguments de la recherche ne sont pas gardés.
- À revoir au-delà de 20 000 faits du monde environ, ou si l'index passe sur disque.

*Pourquoi :* les nouvelles lues pour sa propriétaire ne laissaient rien, et l'on craignait que le monde noie ses proches.

*Révise 0085 (en partie).*

### 0111 — Une échelle de similarité commune à tous les modèles

- L'index rend une similarité centrée sur le fond du modèle (la médiane face à 64 phrases sans rapport, par requête) : 0 pour un texte quelconque, 1 pour l'identique ; l'ordre ne change pas.
- Une comparaison entre souvenirs passe `document=True` (doublons, fusion de la nuit, confrontation) ; le reste est une recherche.
- Les seuils se lisent sur cette échelle, réglés pour EmbeddingGemma 2 : `recall_floor` 0,35, `strong_cue` 0,65, `dedup_similarity` 0,90, `night_merge_similarity` 0,87.
- Un réglage enregistré sur l'ancienne échelle est à revoir ; le banc se relance à chaque changement de modèle.

*Pourquoi :* chaque modèle a son échelle, et avec Gemma l'ancien seuil laissait tout passer.

*Révise 0109 (en partie).*

### 0153 — Ce qui écrit sur elle hors du pipeline sait qui elle est, et en juge

- Sa persona est lue partout où un appel écrit sur elle ou pour elle hors du pipeline, par `self.portrayed` : compacte pour relire une conversation (la sienne ou celle d'un téléphone), la fiche d'une personne, le résumé d'un long fil, la réflexion sur ses intérêts, le tri d'un mail ou d'un message Teams et ce que voit la caméra ; complète pour la relecture de la nuit, qui forme ses avis. Une seule phrase la présente, après la consigne (`self.portrayed.intro`).
- Son corps n'a qu'une définition, celle de sa persona : la relecture ne dit plus « elle n'a pas de corps », elle écarte ce que sa persona exclut (une sortie, un repas), ce qui vaut aussi pour une persona incarnée (ADR 0070). Ses exemples restent génériques et ne lui prêtent plus de plat préféré.
- Le modèle tranche ce que des règles tranchaient. L'importance d'un moment, « à fêter » et « chaque année » sont ceux qu'il dit (`_IMPORTANT`, `_FESTIVE`, `_YEARLY` retirées). La caméra dit ce que l'image lui fait (`named_feeling`) au lieu d'une curiosité à 0,15. Le rêve reçoit ce que chaque fragment lui a fait et dit sa sorte (`[RÊVE: …]`, banal si elle manque) : les seuils de `classify` sont partis. Ce qu'elle a lu se montre aussi en réponse, sans regex sur « tu ».
- Restent statiques ce qui protège : `SECRET_MARKERS`, un deuil jamais fêté (`_DEATH`), le format des sorties ; et deux tris : une chose à faire n'est pas un moment de sa vie (`task_words`), un moment est celui de quelqu'un (ce qu'elle dit vivre seule n'en est pas un, ADR 0084). Une fiche se lit, elle ne se recopie pas : une proposition sur la situation de quelqu'un tient si une seule note en porte les mots de situation tels quels, ses autres mots à leur radical près (hors « c'est quelqu'un qui », la tournure que demande la consigne), avec la même négation dans la proposition de la note qui les porte.
- Ni le rêve ni ses lectures ne redisent « tu peux en parler » : la consigne de style le dit. La boucle « diviser par deux jusqu'à tenir » n'a qu'une forme (`ports.llm_budget.fit_by_halving`). La consolidation partage des fonctions de module (`shown_of`, `kept_from`, `twin_of`…) au lieu d'être instanciée par la relecture de la nuit et celle du téléphone.

*Pourquoi :* ces appels écrivaient sa mémoire, ses avis et son ressenti avec son seul nom. La relecture lui niait le corps que sa persona lui donne (son avatar) et lui prêtait des ramen. Des regex et des seuils décidaient à la place du modèle (audit des garde-fous du 2026-10-27, lot 3 ; audit de la persona du 2026-10-28).

*Révise 0019 (en partie : la sorte du rêve), 0055 (en partie : la fiche), 0084 (en partie : le corps), 0085 (en partie : ses lectures en réponse).*

### 0224 — Une conversation lue sur un téléphone qui n'a pas pu être relue attend dans la file des reprises

- La relecture d'une conversation reçue ailleurs (`memory.relayed`, ADR 0120) suit la règle des siennes : une panne qui dure (après trois essais), une réponse illisible ou une sortie partielle va dans la file durable des reprises (`memory.extraction_deferred`), visible et reprenable dans Mémoire › Consolidation ; les éléments valides d'une sortie partielle sont gardés, et l'entrée attend un opérateur.
- Chaque entrée dit sa source (`source` : « thread », le fil ; « relayed », des messages reçus ailleurs, relus par leur numéro au journal) ; un événement d'avant ce champ vient du fil. Chaque processus ne reprend que les siennes, une par passage, et la reprise d'un opérateur garde la source. La file monte de version et se reconstruit depuis le journal, sans migration. Ses personnes, clés `phone:` comprises, la font oublier.
- Ses messages ne l'attendent plus (`memory.relayed_read`, `failed` quand rien n'en est gardé) : la file les porte.

*Pourquoi :* trois échecs perdaient une conversation du téléphone pour sa mémoire, sans trace visible ni reprise possible, alors que la doc annonçait la file durable (audit du 2026-11-05 : K4-01, décision K4-Q1). Elle complète l'ADR 0120, qui ne disait rien des échecs.

### 0263 — Ce que le fil montre encore ne se redit pas

- Une ligne de « CE QUE TU AS DÉJÀ DIT DE TOI » ou de « CE QUI VOUS LIE » nomme les messages d'où elle vient (`memory_items.sources`, les numéros des tours du fil) : tant qu'elle est fraîche et que l'historique rendu les montre, le composeur l'omet, et la trace le dit (« déjà dans l'historique rendu »). C'est la règle des échanges passés (`Fragment.covered_by`), étendue.
- Fraîche : dite ou redite depuis moins de deux jours (`memory.THREAD_SAYS_IT_US`, `shown_by_thread`). Au-delà, sa mémoire la redit même si le fil la montre encore : dans un fil long, ce qui s'est dit s'y perd.
- Ce qu'elle a dit d'elle : le dernier message où elle l'a dit suffit (une redite complète ses sources). Ce qui vous lie : tous ses messages.
- « CE QUI TE REVIENT » se redit toujours : ce qu'elle a sous les yeux est ce que son usage renforce.
- Un intertitre resté seul (`Fragment.heading`) part avec ce qu'il annonçait, coupé faute de place ou déjà dans le fil.

*Pourquoi :* le prompt réel du 19 novembre 2026 portait les mêmes blagues et le même avis dans ces sections et dans les quarante tours du fil d'où ils venaient ; elle les ressortait.

### 0264 — Sa mémoire et son récit ne recopient pas son portrait

- La relecture d'une conversation ne note pas comme « sur_elle » ce que sa persona dit déjà d'elle : seulement ce qu'elle y ajoute ou en change.
- Son récit dit ce que sa vie a ajouté ou changé depuis son portrait, qui le précède dans chaque prompt ; ce que le portrait dit déjà n'a pas à y être redit.
- Deux phrases de consigne (`memory.extraction.system`, `self.narrative.system`), sans règle dans le code. Ses passions et ce qu'elle sait d'elle restent la matière du récit (0090).

*Pourquoi :* un trait du portrait, redit par elle, était noté comme une note sur elle, repris par le récit de la nuit, et revenait dans son prompt par trois sections ; chaque redite le remettait en tête de la matière du récit.

*Révise 0087 (en partie), 0090 (en partie).*

## Identité et divulgation

### 0012 — La confiance se prouve ; le modèle ne peut que douter

- Une adresse parle pour elle-même, aussi sûre que son transport prouve le compte ; le nom qu'elle donne n'y change rien.
- Se dire une autre personne est une revendication : notée, montrée avec réserve, elle n'ouvre rien.
- La confiance ne monte que par des preuves que le noyau mesure : une session, un lien d'opérateur, un recoupement avec un souvenir privé ; jamais en salon.
- Le modèle ne peut que baisser la confiance (`identity_doubt`, `identity_forget_binding`) ou s'informer (`identity_whoami_with`), jamais accepter une identité.
- Revu par l'ADR 0035 : un recoupement demande deux preuves sur deux messages, et un opérateur confirme la liaison.

*Pourquoi :* en v1, accepter une identité était un outil du modèle : un imposteur n'avait qu'à demander à être reconnu.

*Révisée par 0035.*

### 0035 — Qui parle, et ce qui lie : identité, propriété, lecture de l'autre, liens

- Être convaincue se mérite sur deux messages, jamais dans celui qui revendique ; un détail rare compte plus qu'un nom ou un mot courant.
- Une liaison par recoupement attend la confirmation d'un opérateur : d'ici là, ni le fil des autres adresses, ni d'écriture d'elle-même par là. Une phrase ne délie ni ne renomme.
- Les droits de propriétaire tiennent à l'adresse qui parle (session d'opérateur, adresse prouvée ou reliée par un opérateur), jamais par recoupement, jamais en salon public.
- Ce qui change la confiance (relier, délier, déclarer une proximité) s'annonce et exige « Je confirme ».
- La proximité se lit sur une fenêtre glissante ; « proche » demande un mois d'histoire. Sa propriétaire est une amie d'office, jamais proche d'office.

*Pourquoi :* un imposteur se faisait lier en un message, et les droits de propriétaire passaient par la personne plutôt que par l'adresse.

*Révise 0012 (en partie), 0013 (en partie).*

### 0075 — Un prénom se présume, il ne se relie pas

- À l'extraction, un nom ne se relie qu'à un locuteur, un nom complet unique, ou un prénom unique vu en salon avec la conversation ; sinon il reste une mention `name:<portée>:<prénom>`.
- L'identité présume la seule personne connue de ce nom (`identity.presumed`), relu à chaque fois, sans événement : une homonyme ou un opérateur la font tomber.
- Une présomption sert à y penser, jamais à la traiter comme elle : le rappel la range sous la personne présumée, avec son doute ; ni fiche, ni portrait, ni `social.TIES`.
- Une présomption ne protège jamais moins qu'une liaison (dans le doute, rien ne s'ouvre), et l'oubli d'une personne emporte les mentions présumées être elle.
- Une croyance naît bornée par sa nature : 0,8 dite, 0,9 vue ou vécue, 0,6 déduite ; seul un autre témoin la fait monter, jusqu'à 0,95.

*Pourquoi :* un prénom relié d'office faisait de la collègue de Bob l'amie qu'elle connaît.

*Révise 0074 (en partie).*

### 0092 — Nommer exige un lien ; raconté, c'est dit ; ce qui se reconnaît

- La vie d'autrui ne se dit nommément, au-delà de l'anodin, qu'à qui a un lien déclaré avec la personne ou qui était là ; sinon sans nom, ou pas. Facette `untied_level`, que toute audience réelle précise.
- Elle vaut pour ce qu'elle sait, pense, rêve ou pourrait dire de quelqu'un ; projets, buts, monde et fichiers gardent la règle d'une amie (ADR 0058).
- Raconté, c'est dit : un récit sans nom compte pour dit si sa réponse en reprend la moitié des mots ; montré seulement, non. Un récit déjà raconté repasse le verdict.
- Le filet écarte aussi mois, jours et mots à majuscule (ou qui en portaient une) ; une amie commune ferme au second degré, une relation finie ou hostile au premier.
- Une demande de silence couvre ce qu'elle vise, pas toute la conversation ; un secret posé hors demande devient au moins une confidence.

*Pourquoi :* une amie de Mika entendait nommément la vie de gens qu'elle ne connaissait pas, et un silence demandé en taisait trop.

*Révise 0058 (en partie), 0091 (en partie).*

### 0133 — Qui peut quoi : un moteur, des types de règles, une page

- **Un moteur** (`vocab.access.decide`) : un tableau est fait de lignes lues de haut en bas, comme les règles d'un pare-feu, et d'une **ligne par défaut**, obligatoire ; la première ligne qui correspond décide, et la décision dit sa ligne (le pourquoi). Ce qui correspond dépend du type de règles : la personne en face et le moment (`facing` : les sources que la ligne coche, et quand elle vaut), ou le destinataire d'un envoi (`vocab.sending`).
- **Les sources** : une ligne en coche une ou plusieurs — toi ; elle, quand elle travaille seule (pour toi) ; tes proches (un lien « proche »), authentifiés, en privé ; tout le monde ; des personnes par leur nom, authentifiées. **Quand** ne dit plus que des moments (quand elle répond, quand elle prend la parole ; aucun : toujours) : le travail est une source, plus un moment. Une ligne d'avant se traduit à l'identique (`upgrade`) : « toi » devient toi et elle qui travaille, selon ses moments ; « les comptes » (toute personne authentifiée en tête-à-tête) reste lisible tant qu'on ne l'a pas changée, et ne se coche plus.
- **Des types de règles**, chacun chez son propriétaire et déclaré (`Faculty.rights`) : ses tableaux en mots, et ce qu'ils accordent à qui est en face. Aujourd'hui : les services (0131), ce qu'elle envoie à ta place (0132), les projets et leurs apps. La grille des règles d'outils par situation (0122) reste à part : elle ne fait que restreindre.
- **Une porte pour les outils** : celle d'offre (`runtime.tool_offer.offer`), dont la condition `ToolSpec.fits(audience, kind, frame)` lit ces règles, journal compris ; le gestionnaire revérifie par la même règle. Prêter à un agent suit aussi les règles d'outils de l'opératrice qui prête. La garde `min_level` des outils, qu'aucun n'employait, est retirée.
- **Des planchers**, dans le code, qu'aucune ligne n'ouvre : agir (un outil, changer un projet, se servir d'une app) jamais dans un salon, avec une inconnue ni sans personne — « tout le monde » n'y ouvre qu'à voir et lire un projet ; une app qui a des secrets ne sert en conversation que promue ; un `[À COMPLÉTER` attend toujours un accord ; ce que le téléphone envoie, c'est toujours ton geste ; le plancher des images (0063). À qui elle rend compte (une annonce de courrier, un compte rendu de réveil ou de projet) reste une affaire de propriétaire et de confidentialité, pas de règles.
- **Ce que le code réserve à sa propriétaire** est un seul plancher (`vocab.access.owner_here`), pour le courrier, Teams, la caméra, les flux et la Forge (écrire et régler ses apps) : toi en privé — jamais dans un salon, même toi —, ou elle qui travaille pour toi ; un projet ou un réveil seulement s'il a pris ce lot, une tâche seulement si c'est l'une des siennes (un brouillon, la lecture de la file d'une app). La page « Droits » lit ces outils sur eux-mêmes (`owner_only`, `when`), jamais une liste recopiée.
- **Un projet** a ses lignes d'accès, journalisées (`projects.access_set`), réglées sur sa fiche (onglet « Accès », `projects.acces`) : ses sources, quand, le voir, le piloter (« Piloter projet » : lecture seule, accord du propriétaire, modification, aucun pilotage), ce qu'elle fait d'un outil de ses apps qui lit et d'un outil qui agit (seule, demande à la personne, ton accord, non), et à quels outils (tous, ou une sélection `<app>_<outil>`). Voir et piloter valent quelle que soit la sélection d'outils.
- **Voir** : elle peut en parler à cette personne, sa confidentialité filtrant encore ce qu'elle en dit ; dans un salon ou devant une inconnue, seules « tout le monde » et la ligne par défaut le disent — en parler n'est pas agir. **Piloter projet**, toujours avec « voir » : *lecture seule*, elle en dit le détail (son dernier compte rendu, ce qui vient — `access.reads`), comme voir, aussi dans un salon pour « tout le monde » ; ses demandes — une consigne, un objectif, une pause, une reprise, « vas-y maintenant » (`project_steer`, seulement quand elle répond, quel que soit « quand »), jamais son cadre (titre, outils, accord), qui reste à la console — sur *l'accord du propriétaire* sont proposées (`projects.steer`, son aperçu exact, dans la console) et s'écrivent une fois acceptées ; en *modification*, elles s'écrivent aussitôt, au nom de qui les a faites. Toi en face, l'accord du propriétaire, c'est le tien : ta demande s'applique aussitôt. Pour elle qui travaille seule, voir et piloter ne comptent pas (elle y travaille) : seules les colonnes des apps.
- Un projet jamais réglé : toi et elle qui travaille, tout ; les autres l'entendent selon sa confidentialité, en lecture seule, sans se servir de ses apps. Une ligne ajoutée est fermée.
- **Les apps suivent leur projet** : un outil d'app (`<app>_<outil>`, `<app>_pages`) est offert selon la ligne de son projet qui le concerne — sa colonne « lecture » si l'app le déclare (`lit: true` dans son manifeste ; ses pages lisent toujours), « action » sinon. Une app sans projet : toi et elle qui travaille, toujours, seule. Sur accord, l'appel est proposé (`forge.call`, son aperçu exact : l'app, sa version, l'outil, les arguments) ; exécuté, ce qu'il a rendu revient comme un contenu (`forge.answered`) qu'elle dit à qui l'a demandé. Les planchers de l'app (arrêtée, cassée, des secrets sans promotion en conversation) restent.
- **La page « Droits »** (Réglages) lit ces déclarations, jamais une recopie : par ressource (chaque tableau, ses planchers, où il se règle), par personne (toi quand elle répond ou prend la parole, chaque personne qui a un compte avec son lien tel qu'il est, un autre compte, une inconnue, un salon, quand elle travaille seule : ce qu'elle a, et la ligne qui en décide), les règles d'outils par situation, et ce que le code fixe.
- Rien d'avant n'est repris : sa mémoire et ses réglages repartent de zéro (2026-10-25). Le journal ne se traduit plus (un message Teams remarqué dit seulement `prepare`), ni les réglages : une fiche de service d'avant les ADR 0131 et 0133 (« avec qui », « toi », « les comptes », le moment « travail ») est refusée, une décision d'outil d'avant aussi ; les surcharges de la recherche web (« pour qui », « quand elle travaille »), l'accord avant un envoi de courrier, « préparer d'elle-même », « jamais pour » et le mode de Teams ne se lisent plus en règles (ce que disaient les ADR 0131 et 0132).

*Pourquoi :* « est-il possible d'unifier le moteur de règles ? … une consultation globale des droits sur une page dédiée, et un point d'entrée unique pour vérifier si on a le droit » ; trois tableaux de lignes (services, envoi, projets) appliquaient chacun la même idée à sa façon, et ce qu'une personne pouvait faire ne se lisait qu'en ouvrant chaque page. Puis « pour la source il y a normalement : tout le monde, propriétaire, en privé (amis proches), elle qui travaille, personne (liste des personnes) », cinq vérifications « propriétaire » écrites chacune à sa façon, et « Piloter projet : lecture seule, accord du propriétaire, modification, aucun pilotage ».

*Révise 0104 (en partie), 0122 (en partie), 0131 (en partie), 0132 (en partie). Révisée par 0134, 0148, 0189, 0257, 0268, 0282, 0289, 0290.*

### 0134 — Qui, par où, quand : deux portes, six sortes de tableaux

- **Un cadre pour toute règle** (`vocab.access`) : une ligne dit **qui** est en face (toi ; tes proches ; une personne par son nom ; tout le monde — pour un canal de messagerie, aussi une adresse ou un @domaine), **par où** ça arrive (un canal : le chat web, l'app Android, Teams, le courrier, Internet, elle seule — un type, ou une instance `type:clé` pour une exception, « tous » sinon) et **quand** (elle répond, elle prend la parole ; rien : toujours). Lues de haut en bas, la première qui correspond décide, sinon la ligne par défaut, fermée. « Elle, quand elle travaille seule » n'est plus un « qui » : c'est le canal « elle seule » (`interne`), sans personne ni moment.
- **Ce qu'un canal prouve tient au moyen de communication, pas au type** : reconnu = une session du chat web, le jeton de l'app Android, ou un moyen qu'un opérateur a relié à la personne (une adresse mail aussi : permis, signalé — une adresse s'usurpe). Non reconnu = une inconnue. Dans un salon ou à plusieurs, personne n'est reconnu, même toi. Le minimum vital d'Internet le dit : toi (une adresse déclarée, ou qu'un opérateur t'a reliée : 0035), tout ; les autres, répondre et un outil qui lit — le plafond d'une inconnue fait le reste.
- **Des plafonds, dans le code, que la page montre en cases grisées** (jamais une phrase ailleurs) : une inconnue n'obtient au plus que des outils qui lisent, jamais une action, une garde « rien », un projet en lecture seule, pas de fichier ; à plusieurs, un de ses propres outils qui lit au plus, rien de ce qui vient d'ailleurs (des témoins), un projet en lecture seule au plus ; sans personne en face hors du travail, rien. Seule « tout le monde » désigne une inconnue ou un salon.
- **Deux portes** : une demande passe par le tableau du **canal** par où elle arrive, puis par celui de la **ressource** qu'elle touche ; la plus stricte gagne (`vocab.access.tighten`), et la décision dit les deux lignes.
- **Six sortes de tableaux**, un moteur : les **canaux** (`vocab.canals`, rangés dans les réglages ; ses colonnes sont des plafonds : répondre, outils qui lisent, qui agissent, projets, fichiers, garde — et, pour tes comptes de courrier et Teams, préparer d'elle-même et comment ça part : « Envoyer à ta place » est le tableau de canal de tes comptes, l'ADR 0132 s'y fond) ; **ses propres outils**, un tableau par famille (lot), pré-rempli du **minimum vital** que le code déclare (`owner_only` : la famille naît à toi et elle seule ; sinon à tout le monde et elle seule), modifiable, avec « Revenir au minimum vital » et un avertissement en dessous (l'ADR 0122 s'y fond : « retiré » est une ligne à « non » ; « en main / à chercher » devient un réglage de l'outil, plus une grille par situation) ; les **services** (0131, avec « par où ») ; les **apps sans projet**, un tableau par app, journalisé (`forge.access_set`), né à toi et elle seule, avec une garde ; les **projets** (0133, avec « par où » et une colonne **fichiers**, qui remplace « toi, ou qui l'a confié ») ; et les apps d'un projet, qui le suivent.
- **Un outil dit s'il lit ou s'il agit** (`ToolSpec.acts`) : sa colonne. Un accord (« ton accord », « demande à la personne ») ne se règle que pour un outil qui se diffère (un effet proposé) ; les autres ont la case grisée : « cet outil ne se diffère pas ». La garde est grisée pour ce qui est déjà à elle (sa mémoire, ses fichiers).
- **La porte d'offre reste la seule** (`runtime.tool_offer.offer`) : plafond, canal, famille, puis la condition de la ressource (`fits`). `owner_only` et `when=offered` n'y sont plus des planchers : le premier déclare le minimum vital, le second disparaît des outils qui agissent (le plafond le dit) — `project_files`, qui ne liste que ce qu'elle pourrait envoyer, garde sa condition (rien à lister dans un salon ni pour une inconnue), comme douter garde la sienne. Un gestionnaire revérifie par la même règle.
- **Restent hors tableau** : le plancher légal des images (0063), le geste du téléphone, `[À COMPLÉTER` → un accord, la confidentialité qui filtre ce qu'elle dit, le cadre d'un projet (la console), le lot qu'un projet ou un réveil doit avoir pris pour qu'elle seule s'en serve (dit sur la ligne « elle seule »), l'état d'un objet (outil suspendu, app cassée, app à secrets non promue : une raison affichée). Les délégations (un réveil par API, un agent prêté : tes droits, dans ce qu'ils déclarent) se lisent en lignes dérivées.
- **La page Réglages › Droits** lit les six sortes, ressource par ressource (sa vie interne, les apps de la Forge, les services MCP, ses projets, ses canaux), chaque outil décrit, avec le détail des accès de chacune (son tableau tel qu'il est écrit, « Modifier » vers la page qui le règle) ; les droits exacts, outil par outil, seulement quand on a choisi qui et par quel canal — la règle du moteur, les deux lignes qui décident, le canal ou le plafond quand ils serrent. Ses propres outils se règlent dans Outils › Ce qu'elle peut faire, famille par famille (« Régler les droits ») ; ses canaux dans Réglages › Canaux.

*Pourquoi :* « un salon n'existe pas dans la sélection de qui ? » — « qui » mélangeait la personne et la situation, et cinq règles restaient cachées dans le code ; « il faudrait rajouter canal source » ; « ils doivent aussi avoir leur tableau de droits » (sa boîte mail, Internet, chaque app sans projet) ; ses propres outils sont « le minimum vital : pré-rempli, modifiable, et dépendant du moteur de droits comme le reste ».

*Révise 0122 (en partie), 0131 (en partie), 0132 (en partie), 0133 (en partie). Révisée par 0148, 0184, 0185, 0220, 0226, 0257, 0309.*

### 0148 — Ce qu'un outil exige de qui est en face, il le déclare

- Un outil dont le gestionnaire refuse selon qui est en face, au-delà de ce que le plafond dit déjà, déclare cette condition (`ToolSpec.when`) : l'offre la filtre (le modèle n'est plus invité à ce qui refusera), le gestionnaire la revérifie par la même fonction, la console la lit (la première phrase de sa docstring).
- Les messages de ton téléphone (les lire, y préparer une réponse) : la personne dont c'est le téléphone, authentifiée, en tête-à-tête. Une position : celle de qui lui parle, en tête-à-tête, authentifié. Une ligne qui ouvre leur famille à tes proches ou à tout le monde ne les offre ni dans un salon, ni à une inconnue, ni pour le téléphone d'une autre.
- Dessiner et montrer un dessin n'en ont pas besoin : ils agissent, et le plafond les garde déjà d'un salon et d'une inconnue (0134). Ce que le gestionnaire de `draw` revérifie (le plancher légal, le contenu adulte pour toi seule, les dessins du jour d'une autre personne) se dit par sa règle (`rule`).
- La page « Droits » montre aussi la condition d'un outil réservé (`owner_only`) : réservé et gardé à la fois.

*Pourquoi :* les outils du téléphone et de la position refusaient dans leur gestionnaire ce que l'offre et la page « Droits » disaient permis dès qu'une ligne les ouvrait : un outil qui lit passe le plafond d'un salon et d'une inconnue (audit des garde-fous du 2026-10-27).

*Révise 0133 (en partie : ce que la page « Droits » montre d'un outil réservé), 0134 (en partie : une condition qui dit plus que le plafond reste, même sur un outil qui agit).*

### 0184 — Elle est une personne : dans « qui », par son nom

- Dans un tableau de droits, elle se coche dans « qui » comme une personne, sous son nom (`vocab.access.SELF`, « elle » dans le journal, son nom de persona dans la console : `ui.her_name`). Une ligne d'elle seule est **elle, par le canal « elle seule »** : la colonne « qui » n'y est plus cachée (« — »), seule la colonne « quand » se tait (au travail, les moments ne comptent pas).
- Elle ne désigne qu'elle seule, au travail (`designates` : la situation `travail`) ; une ligne peut la cocher avec d'autres (« toi et elle »). Le formulaire refuse une ligne sans « qui », une ligne « elle seule » qui coche quelqu'un d'autre qu'elle, et une ligne qui la coche sur un canal par où elle n'arrive jamais.
- Les minimums vitaux l'écrivent ainsi (`vital_family`, les canaux, les services, les projets, la Forge). Une ligne réglée avant, sans personne par le seul canal « elle seule », vaut toujours pour elle (`alone`) et s'affiche elle cochée : enregistrée, elle s'écrit comme les nouvelles.

*Pourquoi :* « il faudrait que l'IA soit considérée comme une personne (on reprend son nom dans le sélecteur) » — la colonne « qui » restait invisible quand on voulait lui donner des droits à elle.

*Révise 0134 (en partie : elle est de nouveau un « qui », par le canal « elle seule »).*

### 0185 — À qui est une boîte : elle sert à son propriétaire

- Une boîte aux lettres est **à toi** (ses propriétaires, par défaut), **à elle**, ou **à une personne qui a un compte** (`MailAccount.owner` : vide, `elle`, `personne:<clé>` ; « À qui », dans Courrier › Paramètres, vérifié à l'enregistrement). Ce qui en dérive est journalisé avec ses autres paramètres (`EmailParams.owners`).
- **Elle s'en sert avec son propriétaire** (`plugins/email.boxes_here`) : les tiennes là où sa famille d'outils le permet, comme avant (toi en privé, elle quand elle travaille, qui une ligne de la famille ouvre) ; les siennes quand elle travaille ; celles d'une personne seulement avec elle, reconnue, en tête-à-tête ; une tâche de rédaction, la boîte de son mail. Ouvrir les tiennes à d'autres reste l'affaire du tableau de la famille Courrier (Outils › Ce qu'elle peut faire) ; la boîte d'une autre personne ne s'ouvre à personne d'autre.
- **Ses outils de courrier sont offerts à qui a une boîte à son nom** (`ToolSpec.owned`, `runtime.tool_offer.owns` : une ressource de l'outil est à qui est en face), même quand sa famille ne l'ouvre pas ; son gestionnaire ne lui montre que ses boîtes (`plugins/email/boxes.Boxes`, le port réduit) — ni les mails, ni les dossiers, ni les brouillons, ni les envois d'une autre. Ses sections de prompt filtrent de même.
- Elle n'annonce un mail important (une initiative envers sa propriétaire) que d'une de tes boîtes ; elle ne prépare d'elle-même une réponse que dans les tiennes et les siennes. Comment ça part reste le tableau du canal de la boîte (Réglages › Canaux), un accord par défaut ; **l'accord est au propriétaire** : pour la boîte d'une personne, la carte va dans son chat à elle (`approver_of` : une de ses adresses présente, sinon une où l'on peut lui écrire), et elle sait que c'est cette personne qui approuve (`approver_name`) ; pour les tiennes et les siennes, toi, comme avant. Un opérateur décide toujours aussi dans la console (À valider).
- **La console** : la fiche d'une personne a l'onglet « Comptes » quand une boîte est à elle (la vue `boites` du courrier ; ses propriétaires : les boîtes sans propriétaire nommé — un onglet de fiche peut lire ce qu'elle vit : `InspectSpec.shown(tranche, clé, frame=…)`) ; Courrier (réception, brouillons, envoyés, contacts) se lit par propriétaire, « Les boîtes de » (`?qui=` : tout le monde, toi, elle par son nom, chaque personne qui a une boîte).

*Pourquoi :* « on peut lui associer à elle des comptes en toute autonomie comme pour les autres » — une boîte avait une voix (« elle écrit en son nom, en assistante, à ta place ») mais pas de propriétaire ; et une personne ne pouvait pas avoir la sienne sans que tu la lises.

*Révise 0134 (en partie : une ressource à quelqu'un est offerte à son propriétaire), 0173 (en partie : « À qui » dans la fiche d'une boîte). Révisée par 0186, 0188, 0191, 0207 (en partie : sa propriétaire règle comment part ce qu'elle y prépare, dans Paramètres), 0219 (en partie : l'onglet Comptes paraît aussi pour un service ou un partage).*

### 0186 — Un Teams par personne : un compte sert à son propriétaire

- Plusieurs comptes Teams (`TeamsConfig.accounts`, une clé en minuscules ; « Actif » reste commun à tous). Chacun a son nom, **son propriétaire** (vide : toi ; `elle` ; `personne:<clé>`, vérifié comme une boîte, 0185) et sa voix (nom, ton, consignes, signature).
- **Une clé d'extension par compte** (`Settings.teams_keys`), créée et retirée dans Teams › Extension, sur le compte (`teams.cle`, `teams.retirer_cle`), ou par `mika teams key|revoke --compte <clé>`. La porte reconnaît le compte à sa clé, toutes les clés comparées en temps constant ; son plafond par minute est par compte. Ce que l'extension pousse, relève et accuse ne concerne que son compte ; une réponse part du compte de sa conversation, sous le nom de sa personne. Le protocole de l'extension ne change pas.
- Chaque ligne de `teams.db` porte son compte (une table `accounts` remplace `meta`) ; une conversation se désigne par (compte, identifiant) — `<compte>~<id>` dans la console ; une référence de message est unique entre les comptes. **La reprise** : ce qui existait devient le compte `principal`, à toi, l'ancienne clé unique est la sienne et la configuration d'avant sa voix ; une référence déjà au journal reste valable.
- **Elle s'en sert avec son propriétaire** (`plugins/teams.accounts_here`, la règle de 0185) : les tiens là où sa famille d'outils le permet ; les siens quand elle travaille ; celui d'une personne avec elle seule, reconnue, en tête-à-tête ; une tâche, le compte de son message. Ses outils réservés sont offerts au propriétaire d'un compte (`owned`) et ne voient que les comptes visibles (`plugins/teams/accounts.Accounts`) ; ses sections de prompt filtrent de même.
- Elle remarque les messages de tous les comptes (des signaux comme les autres) ; d'elle-même, elle ne prépare une réponse que dans les tiens et les siens. Dans son propre compte, elle écrit **en son nom** (`teams.voice.own`), pas à la place de quelqu'un, et le tri lit ses messages comme les siens (`teams.triage.intro_own`). Pour le compte d'une personne, la carte d'accord va à cette personne : c'est sous son nom que le message part ; un opérateur décide toujours aussi dans la console (comme le courrier, 0185). Le tableau du canal du compte (`teams:<clé>`) s'applique, et Réglages › Canaux le propose comme une boîte.
- **Un compte se décoche** (« Actif », `TeamsAccount.enabled`, journalisé : `TeamsParams.accounts_off`) : la porte refuse son extension, rien n'arrive ni ne part, elle n'y prépare ni n'y propose rien ; ses conversations, ses réglages et sa clé restent. **Un compte supprimé** des réglages emporte ce que son extension avait apporté (`TeamsPort.drop_account` : ses conversations, ses messages, ses brouillons).
- **La console** : chaque onglet de Teams commence par « Les comptes de » (`?qui=` : tout le monde, toi, elle par son nom, chaque personne qui a un compte Teams), puis le compte (`?compte=`) quand il y en a plusieurs ; Extension, un compte par ligne, ou le compte choisi avec sa clé et le pas-à-pas ; Réglages › Teams, « Actif » puis les comptes en cartes (à qui, clé, dernier envoi). La fiche d'une personne réunit ses comptes Teams à ses boîtes sous « Comptes » (sans boîte, « Teams » est un onglet à lui).

*Pourquoi :* « un onglet Ses comptes email, son plugin Teams » ; « on puisse sélectionner l'utilisateur pour voir ses comptes » — et le choix d'un Teams par personne, chacune avec sa clé, plutôt qu'un seul Teams attribué.

*Révise 0069 (en partie : un compte par personne), 0185 (Teams suit la même règle). Révisée par 0188, 0191, 0206, 0219 (en partie : un service ou un partage fait paraître Comptes, où Teams se joint).*

### 0188 — Partager ce qui est à soi : lire, lire et préparer, s'en servir

- Qui possède une boîte, un compte Teams ou un service MCP le partage avec une personne qui a un compte, à l'un de trois niveaux : **lire** (elle le voit dans son propre Mika, sans répondre ni ranger), **lire et préparer** (Mika lui prépare aussi des réponses, que le propriétaire approuve, 0191), **s'en servir** (Mika s'en sert pour elle, en tête-à-tête, comme pour son propriétaire).
- Un partage est rangé avec sa ressource et journalisé avec ses paramètres, comme son propriétaire (0185, 0186) ; il se retire d'un clic. Le propriétaire voit les siens dans Paramètres › Partages, la console les voit tous.
- La règle du propriétaire s'étend à qui l'on partage : une boîte, un compte servent aussi avec elle, reconnue, en tête-à-tête (`boxes_here`, `accounts_here`), à son niveau — lire n'ouvre que ce qui lit ; préparer, aussi les brouillons ; s'en servir, comme le propriétaire, sous le tableau du canal de la ressource. Un service partagé reçoit une ligne d'accès pour elle (0192).
- Rien ne se partage avec un salon, une inconnue, ni « tout le monde » ; ce qu'on te partage se montre à son nom (« Boîte de Léa »). Le non-lu d'une boîte partagée est celui du serveur : commun.
- Une ressource « à toi » est déjà à chacune de ses propriétaires : elle ne leur est pas partagée, et ce qu'elles y font n'attend jamais l'accord d'une autre. On ne se partage rien à soi-même.
- Répondre à la main à un mail (ce qui demande « s'en servir ») refuse les brouillons de Mika qui attendaient pour ce mail, quel que soit qui répond, et remplit la demande d'une réponse (« Préremplir ») : celle qu'elle finirait au travail ne se propose plus — relue au moment même de la proposer, même si la réponse est partie pendant qu'elle l'écrivait. La réponse se garde avec le mail (pas seulement parmi ses derniers envois) : elle ne lui en prépare pas d'autre. Rien ne part deux fois. C'est la seule fois où un partage touche aux brouillons du propriétaire.

*Pourquoi :* « pour y gérer ses droits sur ses comptes : ex rajouter en lecture quelqu'un (et ça s'affichera dans son frontend à la personne) ou même partager son MCP » — une boîte de personne ne s'ouvrait à personne d'autre (0185).

*Révise 0185 (en partie : la boîte d'une personne s'ouvre à qui elle la partage), 0186 (en partie : de même pour un compte Teams). Révisée par 0199 (en partie : répondre soi-même dans Teams refuse aussi ses réponses en attente), 0200 (en partie : une boîte partagée en lecture reste hors de tes vues communes, et répondre à la main refuse ses brouillons dans l'action du courrier, console comprise), 0210 (en partie : un opérateur voit tous les partages dans Réglages › Droits › Partages, et retire ceux d'une boîte ou d'un compte Teams).*

### 0207 — Comment part ce qui part de ses comptes : sa propriétaire le règle

- La propriétaire d'une boîte ou d'un compte Teams (le sien, ou « à toi » pour une de ses propriétaires : 0185, 0186) règle elle-même, dans Paramètres (frontendv2), comment part ce que Mika y prépare : pour chaque ligne de la règle de son canal (`courrier:<clé>`, `teams:<clé>`) et pour sa ligne par défaut, **préparer d'elle-même** et **comment ça part** (seule, ton accord, brouillon — Teams seulement —, non). Qui écrit, quand, l'ordre et le nombre des lignes restent à la console (Réglages › Canaux), qui garde tous les réglages.
- Par `POST /api/moi/rules`, limité à ses comptes : un partage n'y suffit pas, ni un autre canal. La règle qu'elle voit est celle que le courrier et Teams lisent — celle du compte, sinon celle de tout son canal, sinon le minimum vital — avec son empreinte, qui doit être celle d'aujourd'hui pour l'enregistrer : réglée entre-temps dans la console, elle se relit d'abord. Enregistrée, elle devient la règle du compte : celle de tout le canal ne vaut plus pour lui. Le courrier n'a toujours pas de brouillon que tu envoies toi-même (0132) : une ligne ne le devient pas d'ici.
- C'est un réglage du compte : il s'audite comme lui (`moi.boite`, `moi.compte_teams`), se rejournalise aussitôt, et vaut pour ce qu'elle prépare ensuite (ce qui part relit la règle d'aujourd'hui, 0132).

*Pourquoi :* depuis les ADR 0185 et 0186, un compte a un propriétaire et ses droits le suivent ; sans console, elle ne pouvait pas régler ce qui part de chez elle (audit du 2026-11-05, décision Q22).

*Révise 0132 (en partie : sur un compte qui a une propriétaire, elle règle préparer et comment ça part), 0185 (en partie : comment ça part ne se règle plus seulement dans Réglages › Canaux).*

### 0220 — Un outil du code ne se diffère pas

- Un outil du code (`@f.tool`) agit dans la conversation même, ou propose une capacité (`@f.capability`) qu'un accord décide après le commit : Envoyer à ta place (0132), À valider.
- Il ne se diffère jamais lui-même : `ToolSpec.deferrable` et le paramètre `tool(deferrable=…)` sont retirés, comme `ToolSpec.effect` (`EffectClass`), que rien ne lisait. S'il faut un jour différer un outil du code, une décision le rouvrira.
- Seuls les outils d'un service (0131) ou d'une app de la Forge (0134) demandent eux-mêmes un accord, par une carte ; en mode pro, la boucle attend celui d'un service (0165).
- Dans Outils › Ce qu'elle peut faire, « ton accord » et « demande à la personne » restent grisées pour toutes ses familles (`inspector/pages/families.py`) : rien ne change à l'écran.

*Pourquoi :* aucun outil ne posait le champ, et la page gardait une branche qui ne pouvait pas servir ; un champ que personne ne pose fait croire qu'il compte (audit du 2026-11-05, décision K1-Q1).

*Révise 0134 (en partie : un accord ne se règle pour aucun de ses propres outils).*

### 0226 — La colonne d'un outil dit ce qu'il ouvre : son journal lit, douter reste avec ce qui lit

- `ToolSpec.acts` choisit la colonne d'un tableau de droits (« un outil qui lit », « un outil qui agit ») et le plafond qui s'y applique ; c'est ce que disent Réglages › Droits, Outils et `/api/moi/rights` (« elle lit », « elle agit »).
- Relire son journal (`self_journal`) est un outil qui lit. Une condition déclarée (0148, `in_known_company`) le garde d'une inconnue et d'un salon, et son gestionnaire la revérifie. Par Internet, quelqu'un d'autre que toi compte comme une inconnue, même relié à une personne par un opérateur (rien ne prouve qui écrit) : la condition l'y ferme, comme le plafond d'une action le faisait. Qui peut le lui faire relire en conversation ne change donc nulle part.
- Douter de qui écrit (`identity_doubt`) et défaire une liaison (`identity_forget_binding`) écrivent une preuve, mais ne font que baisser la confiance (0012) : ils restent dans la colonne « lecture », pour servir devant une inconnue et à plusieurs, là où une usurpation se tente. Aucune garde n'exige qu'un outil qui émet soit marqué `acts`.

*Pourquoi :* l'audit a trouvé deux drapeaux à l'envers de ce que faisaient leurs outils ; les inverser tels quels aurait fermé le doute là où il sert et ouvert son journal aux inconnues (audit du 2026-11-05, K6-01, décision K6-Q1).

*Révise 0134 (en partie : un outil dit s'il lit ou s'il agit au regard des droits ; ce qui ne fait que baisser la confiance se range avec ce qui lit).*

### 0298 — L'annuaire : tous ceux qu'elle connaît, même sans leur avoir parlé

- **Le principe.** L'annuaire réunit toute personne et toute organisation qu'elle connaît, pas seulement qui lui parle : elle connaît quelqu'un dès qu'elle le lit ou qu'on lui en parle.
- **Les sources.** Teams (les auteurs et les personnes mentionnées, dans tous les comptes branchés) ; le courrier (expéditeurs et destinataires des boîtes qu'elle lit) ; le téléphone (expéditeurs des messages WhatsApp et SMS) ; ce qu'on lui raconte (une personne dont on lui parle a sa fiche d'emblée).
- **Deux sortes de fiches** : une personne, une organisation (déduite d'un domaine de courrier ou d'une organisation Teams, avec ses membres).
- **Tout ce qui l'identifie** est sur sa fiche : chacun de ses moyens de communication dit sa sorte (identifiant de compte, identifiant Teams, e-mail, téléphone), d'où elle le tient, et s'il lui parle ou si elle ne fait que le lire ; son organisation.
- **À qui est un contact.** Une personne connue de loin est le contact de qui l'a fait connaître : vue dans le Teams ou la boîte d'Adrien, ou dont Adrien lui a parlé, c'est un contact d'Adrien ; croisée chez deux personnes, elle est le contact des deux ; vue par aucun compte à quelqu'un, elle est à tout le monde. Chacun a ainsi ses contacts : la console les montre sur la fiche, frontendv2 aura son onglet Contacts.
- **Réunir.** Deux fiches se réunissent d'office quand un identifiant le prouve (la même adresse, le même compte Microsoft) ; un même nom seul se propose dans « À valider » (0180), jamais réuni seul : deux homonymes ne se confondent pas.
- **Ce qu'elle en sait** : sa fiche (où elle la voit, combien, quand) et sa mémoire, qui se forme une idée d'elle à partir de ce qu'elle lit — oubliable comme le reste ; oublier la personne atteint aussi ce qu'elle a lu d'elle.
- **Connaître n'est pas parler.** Une personne connue de loin n'est pas une interlocutrice : ni lien, ni attachement, ni initiative envers elle, ni droits. Ce qu'elle a lu ne se dit qu'à qui la source appartient (ce qu'elle lit dans ton Teams ou ta boîte se dit à toi, et à qui tu les partages) ; ce qui ne vient du compte de personne, à tout le monde.
- **Où ils vivent.** Les contacts ont leur propre base (`contacts`), hors du journal, comme le monde de Teams et du courrier : la faculté `identity` reste celle de qui lui parle — son annuaire des interlocutrices, les noms qu'elle présume derrière une mention et l'oubli des inconnues silencieuses supposent qu'on lui a parlé. Le plugin `contacts` les tire des ports (`teams`, `email`, `phone`) ; à qui est un contact se lit à la lecture, sur le compte qui l'a fait connaître. Un contact peut être relié à une personne de l'identité (elle lui parle aussi) : ses identifiants restent les siens, jamais des moyens de communication de l'identité.
- **Les profils Teams.** L'extension joint le profil de chaque personne croisée (nom, e-mail, poste, service, entreprise, organisation Teams, numéros). Son e-mail est la preuve qui réunit sa fiche Teams et celle du courrier : la plus vue est gardée, et jamais deux fiches reliées à deux personnes différentes. Un numéro rejoint sa fiche, sans rien prouver : un standard se partage. Son entreprise nomme l'organisation de son domaine si celle-ci n'a pas encore de nom ; sans domaine (un webmail), la personne rejoint l'organisation de ce nom. Deux organisations qui ont chacune un domaine ne se réunissent jamais par leur nom. L'organisation Teams n'est gardée que si elle porte le nom de l'entreprise : un prestataire peut être hébergé chez un autre. Son poste et son service ne se disent qu'à qui voit ce Teams.
- **Les écrans** sont maquettés d'abord (`output/annuaire-complet/` pour la console, `frontendv2/maquette/` pour l'écran Contacts, qui remplace l'onglet Contacts du courrier), validés, puis codés. Dans la console aussi, Courrier › Contacts disparaît : ses correspondants sont dans l'annuaire, où son adresse mène.
- **Le téléphone.** Un expéditeur WhatsApp ou SMS est le contact de la personne dont c'est le téléphone, et d'elle seule ; il est désigné par sa clé du téléphone sans son nom (renommé dans le carnet, il reste le même), et l'annuaire garde les conversations où elle le lit (un groupe et son nom). La même personne sur WhatsApp et par SMS fait deux identifiants, que leur nom propose de réunir, jamais d'office. Un expéditeur que le téléphone ne nomme que par son numéro *est* ce numéro : la fiche qui l'a le reçoit, et le profil qui le dit réunit la fiche qui n'était que ce numéro — un numéro ne réunit toujours pas deux fiches qui ont un nom. Un numéro se range en E.164 quand c'est un numéro français sans ambiguïté (`06…` → `+336…`) : celui d'un profil Teams et celui du téléphone se retrouvent.
- **Ce qu'on lui raconte.** Une personne dont on lui parle (un nom de sa mémoire) a sa fiche, le contact de qui le lui a raconté (seulement d'un élément qu'on lui a vraiment confié — voir « Relecture » ; jamais d'un expéditeur du téléphone : c'est la personne qui le lui montre) ; son nom s'écrit comme sa mémoire l'écrit. Un même prénom, d'un côté sans nom de famille, se propose aussi, plus faiblement. Relier un nom raconté à quelqu'un qui lui parle reste une décision de l'identité (« C'est la personne dont on lui a parlé ») : sa mémoire le sait, et la fiche du nom suit — « Réunir avec… » une personne y mène ; défait, une fiche qui n'est qu'un nom se délie. Oublier le nom, ou qui l'a raconté, atteint sa fiche.
- **« Noms à relier » devient « Rapprochements ».** Ses couples (un nom raconté, quelqu'un qui lui parle et qui le porte) sont des rapprochements comme les autres, avec leurs deux réponses ; l'onglet disparaît de la file, son adresse y mène.
- **Ce qu'elle en sait, à partir de ce qu'elle lit.** Un rôle `portrait` relit, pour une personne avec qui un compte échange vraiment (des messages dans les deux sens), ses **derniers** messages et en tire quelques faits courts — son rôle, ses sujets, avec quelle équipe elle travaille, ce qu'elle attend, sans nommer personne d'autre —, chacun avec sa source et le compte d'où il vient. Charger l'historique n'en fait relire que la fin ; un réglage de la console l'ouvre à tout l'historique. Les faits sont gardés avec le contact, visibles de qui voit leur source, oubliables un à un ; Mika les consulte quand elle parle à qui la source appartient. Des plafonds par jour bornent le coût, qui se lit dans Système › Appels (rôle `portrait`).
- **Ce qu'elle en sait : ses garde-fous.** Un fait oublié ne se redit jamais au modèle : seule l'empreinte de ses mots reste avec le contact, et le même fait, reformulé, n'est plus gardé. Un premier portrait attend quelques messages ; un portrait sans rien de sûr, ou illisible, laisse les faits d'avant, et la vue attend de nouveaux messages avant d'être relue. Mika les consulte par un outil (`contacts_lookup`), jamais par une section de son prompt : en tête-à-tête seulement, et ce que les comptes de la personne en face en montrent.
- **Ce que l'outil lui dit : de quoi agir** (2026-11-22). Une fiche ne sert pas qu'à savoir qui est quelqu'un : `contacts_lookup` dit aussi comment la joindre (e-mail, téléphone, une adresse générique dite comme telle ; jamais un identifiant Teams ni une clé du téléphone, qui ne sont pas des moyens de la joindre), ses autres noms, combien de fois et quand elle la voit, les conversations où elle écrit — Teams, avec la référence du dernier message que `teams_read` relit ; ses derniers mails, que `email_read` relit ; le téléphone, l'appli et le nom qu'elle y porte —, et chaque fait avec le jour et la référence du message qui le fonde : un fait qui attend quelque chose se juge à sa date. D'une organisation : son domaine, ses adresses génériques et les personnes qu'elle y connaît. La personne de l'identité reliée à la fiche ne se dit qu'à ses propriétaires, qui la voient déjà dans la console, et comme les écrans : « te parle aussi » si elle lui a écrit, sinon « a un compte ». Tout reste dans ce que voit la personne en face. `email_contacts` (le courrier) reste : l'annuaire ne se lit qu'en tête-à-tête, et quand elle travaille seule sur un projet ou une tâche, c'est par lui qu'elle trouve une adresse. *Pourquoi :* l'outil ne disait que le poste, les sources et les faits ; elle ne pouvait ni écrire à quelqu'un, ni relire où il écrit, ni juger si un fait tenait encore (« dans le retour de contacts_lookup, on a bien toutes les informations nécessaires ? »). Le même jour, la famille « contacts » manquait aux outils de la réponse : l'outil n'était jamais offert ; un garde (`test_tools_described`) exige désormais qu'un outil déclaré pour une conversation y soit offert.
- **Relecture : ce qui ne fuit pas, ce qui tient** (2026-11-22). Un nom raconté ne fait une fiche que d'un élément qu'on lui a vraiment confié (`told_by`), ni secret, ni gardé pour elle, ni restreint par ses sources : une réflexion de la nuit ne fait connaître personne, et rien de ce qu'on lui raconte n'est plus « à tout le monde » ; une règle nouvelle relit toute sa mémoire et ce qui ne la suit plus part. Pour quelqu'un, tout se juge sur ce qu'il voit : l'appartenance d'une personne à une organisation ne se dit que si sa preuve (une adresse du domaine, un profil qui dit l'entreprise) est dans ses vues ; le portrait d'une vue nomme la personne comme cette vue la nomme ; l'oubli par l'API se permet sur ce qu'il voit, efface tout si rien ne vient d'ailleurs, sinon sa seule part — même réponse, rien ne dit qu'elle est aussi le contact d'une autre. Ce qu'une opératrice sépare (« Détacher », « Deux personnes différentes ») ne se réunit plus par une preuve, et suit une fiche réunie. Un profil Teams se date par le dernier message de sa personne dans ce compte, jamais par sa réception : un historique rechargé ne ramène pas une personne oubliée. Oublier une personne qui lui parle atteint ses fiches reliées (leurs identifiants, ce que Teams et le courrier en gardent) ; oublier une fiche n'ampute jamais une personne qui lui parle (ni ses moyens de communication, ni un nom que l'identité relie à elle). Elle n'est le contact de personne (ses comptes à elle ne se rangent pas). « Échanger vraiment », c'est un tête-à-tête, ou un petit groupe (huit au plus) où la personne du compte lui répond — jamais un canal —, et chaque compte a son tour sous les plafonds. Un domaine d'hébergement partagé (`*.onmicrosoft.com`) ou un nom de connexion d'invité (`#ext#`) ne fait ni ne nomme une organisation. Un fait ne nomme pas de tiers (la consigne le dit, et un fait qui nomme une autre personne de l'annuaire n'est pas gardé) ; oublier quelqu'un emporte les faits qui le nommaient. « Parle aussi à Mika » ne se dit que de qui lui a écrit ; sinon, « a un compte ».

*Pourquoi :* « toute personne et entité doit apparaître dans l'annuaire, c'est même tout le principe » ; « forcément Mika connaît XXX puisqu'elle lit les dialogues, même si elle ne lui a jamais parlé » ; « associe les contacts à des comptes […] si elle croise le même contact avec deux personnes, il sera lié à deux personnes ; si aucun : tout le monde ».

*Révise 0069 (en partie : les collègues de Teams entrent dans l'annuaire, sans devenir ses interlocuteurs) et 0180 (en partie : les noms à relier se décident parmi les rapprochements).*

*Révisée par 0303, 0304.*

### 0303 — Une fiche qui s'enrichit, un fil qui se remonte

- **La fiche d'un contact se complète au lieu de se refaire.** Chaque portrait recevait seulement les derniers messages de la personne, et ses faits remplaçaient ceux de la même vue : la fiche n'avait jamais plus de six lignes, toutes refaites. Désormais, le modèle reçoit aussi ce qu'elle en sait déjà dans cette vue (ses faits d'avant, « fait 1 »…, numérotés autrement que les messages), puis ses messages, et il rend ce qu'ils lui apprennent.
  - Un fait nouveau cite le message qui le fonde. Un fait d'avant que les messages précisent ou corrigent est récrit (`avant`) ; un fait qu'ils démentent est retiré (`laisse`).
  - **Un fait d'avant que la réponse ne cite pas reste tel quel.** Une réponse partielle, ou mal formée (la CLI de Claude Code ne garantit pas le schéma), n'efface donc rien : seul ce que le modèle retire part.
  - Un fait récrit sans message nouveau garde ce qui le fondait : son message, sa date et quand elle l'avait appris. Un fait précisé prend le message nouveau.
  - Douze faits au plus par vue, et `contacts_lookup` les montre tous, vue par vue.
- **L'oubli atteint toujours la fiche.** Un fait oublié n'est plus dans la fiche, il n'est donc jamais redonné au modèle (0298). Un fait dont le message n'est plus (un message Teams effacé, un mail retiré, un message du téléphone oublié) ne se montre plus au modèle et part au passage suivant, comme avant que la fiche ne s'enrichisse. Après l'appel, la vue se relit : un fait oublié, ou une vue effacée par l'API par personne pendant l'appel, ne revient ni repris ni tel quel.
- **Qui elle est, comment elle est, ce qu'il y a entre eux.** La fiche ne sert plus seulement à répondre à quelqu'un, mais aussi à pouvoir parler de lui. Aux sortes de 0298 (rôle, sujets, équipe, attentes) s'en ajoutent deux :
  - `manner` : son ton, sa façon d'écrire, son humour, ce qui le fait réagir ;
  - `bond` : ce qu'il y a entre lui et la personne du compte (tutoiement, familiarité, ce qu'ils font ensemble, ce qu'il lui demande).
  - Les garde-fous restent ceux de 0298 : rien de deviné, personne d'autre de nommé, la personne du compte dite « la personne du compte ». Rien de sensible, ni sur la personne ni sur celle du compte ; un lien intime ou familial ne se dit que par son ton. Un fait ne se dit toujours qu'à qui voit sa source.
- **Un fil Teams se remonte.** `teams_read` relit les messages jusqu'à une référence (15 par défaut, 40 au plus).
  - La fin dit combien elle en a lu sur combien compte le fil (`TeamsPort.thread_count`), combien sont plus anciens, et la référence du plus ancien lu, jusqu'à laquelle relire pour remonter. Le compte se fait sur ce que la lecture a pris, jamais sur une date : deux messages du même instant ne font pas de trou.
  - Après la référence, seuls ses suivants s'affichent, quand ce sont les derniers du fil (cinq au plus). Plus loin, la fin dit combien restent après, au lieu de montrer la fin du fil comme si elle suivait.
  - Le fil relu tient dans 12 000 caractères, et ce sont les plus anciens qui tombent. Avant, la citation coupait la fin, c'est-à-dire les messages les plus récents et celui qu'on avait demandé.
- Ce qui ne change pas : le portrait ne relit que les messages de la personne elle-même, jamais ceux de la personne du compte. Et seulement les derniers, sauf si l'opératrice coche « Relire tout l'historique ».

*Pourquoi :* le 22 novembre 2026, à « que penses-tu de Kévin Massol ? », elle a résumé sa fiche, six faits de travail pour 310 messages lus, sans ouvrir un seul de ses messages. Relancée (« tu ne peux pas voir les conversations ? »), elle n'a lu que les 15 derniers des 96 messages du tête-à-tête, sans savoir qu'il en restait. « Oui pourquoi pas, c'est pour ça qu'un contact a une fiche. »

*Révise 0298 (en partie : la fiche se complète, deux sortes de plus, douze faits).*

### 0304 — Réunir ses contacts : d'office quand c'est sûr, un juge pour le reste

- **Un identifiant Teams a une seule forme.** Un même compte arrivait parfois sous deux formes (`8:orgid:<uuid>` et
  `worker/8:orgid:<uuid>`, selon le chemin par lequel l'extension l'a lu). Cela faisait deux auteurs dans le cache de
  Teams, donc deux fiches dans l'annuaire : 30 des 66 rapprochements du 22 novembre 2026 étaient la même personne en
  double.
  - Le cache de Teams range l'auteur sous sa forme comparable (`author_key_of`, c'est-à-dire `ports.teams.person_key`,
    celle des profils et des photos), et l'annuaire compare l'identifiant sous la même forme (`normalized`). Le sujet
    d'oubli d'une personne de Teams (`teams.person_handle`) aussi. Le même compte est donc toujours le même auteur, la
    même fiche et le même sujet.
  - Ce qui avait été rangé de travers ne se convertit pas : on l'efface (`mika teams purge` du compte, qui efface aussi
    ses vues dans l'annuaire), puis on recharge l'historique. D'ici là, oublier quelqu'un efface aussi ce qui était
    rangé sous la forme reçue telle quelle.
- **Ce qui n'est pas prouvé est jugé, par le modèle.** Le nom ne prouve rien. Retirer des morceaux de nom (« -EXT »,
  « (Invité) ») ne vaudrait que pour une entreprise. Un juge, le rôle `match` (repli sur `extract`), regarde donc tout
  ce que l'annuaire sait des fiches et dit lesquelles sont la même personne. Le processus `contacts.match` le fait
  toutes les heures, et peu après un message remarqué.
  - Ce qu'il voit d'une fiche : ses noms, son organisation, son poste, ses adresses et ses numéros, et la sorte de son
    compte Teams (de son organisation, invité anonyme d'une réunion, personnel), jamais son identifiant. Il voit aussi
    où et quand elle est lue, où elle écrit dans Teams, l'objet de ses derniers mails, les groupes du téléphone, qui
    l'a racontée et la personne qui lui est reliée.
  - Il rend des personnes (des fiches, s'il en est sûr ou non, et pourquoi) et les paires qu'il sait être deux
    personnes. Sa réponse est relue strictement ; illisible, rien ne change.
- **Ce dont il est sûr se fait seul.**
  - Sûr de la même personne : les fiches sont réunies d'office, comme une preuve les réunirait (`unite`). La réunion
    est gardée (`unions`) ; elle se défait en détachant ses identifiants (« Détacher »), qui en retire aussi la trace.
    Une fiche qui a changé pendant l'appel n'est pas réunie : son avis se refait.
  - Sûr de deux personnes : elles ne sont plus proposées. Ce n'est pas un écart d'opératrice (`dismissed`) : une preuve
    les réunit encore.
  - Sinon, elles attendent dans À valider › Rapprochements, avec son avis en ses mots.
  - Ce qui ne bouge pas : il ne réunit jamais deux fiches qu'une opératrice a séparées, ni deux fiches reliées à deux
    personnes différentes, ni une fiche qui porte un nom raconté, reliée à personne, avec une fiche reliée à quelqu'un
    qui lui parle — même par une fiche intermédiaire (c'est l'identité qui les relie, 0298).
- **Qui il juge.** Les paires des suggestions (le même nom, une initiale, un prénom seul), et celles qui ont des mots
  rares de leurs noms en commun, quelle que soit leur forme (« Kévin Massol » et « Kévin MASSOL-EXT »).
  - Un mot compte s'il a au moins quatre lettres et que dix fiches au plus le portent : « ext », que portent tous les
    prestataires, ne rapproche personne.
  - Il faut deux de ces mots, ou un seul qui n'ouvre pas les deux noms : le même prénom seul ne suffit pas.
  - Par groupes de huit fiches au plus, la plus récente d'abord : un nouveau moyen de communication trouve vite sa
    fiche.
- **Un avis vaut sur ce qu'il a vu.** Chaque avis porte l'empreinte des deux fiches (`bases`, `pair_basis`). Une fiche
  qui change (un identifiant, un nom, une organisation, un lien de plus) est donc rejugée. Une paire ne l'est jamais
  deux fois sur les mêmes fiches.
- **Ce qu'il coûte.** Au plus 5 appels par passage et 40 en vingt-quatre heures, réglables dans Réglages › Paramètres
  avancés › contacts. Le réglage `matching` le coupe : rien ne se réunit alors sans toi, sauf ce qu'un identifiant
  prouve.
- **L'oubli.** Ses avis et ses réunions partent avec leurs fiches, et ceux qui nomment une personne oubliée aussi
  (une raison, le nom d'une fiche réunie), même sur une autre paire. Sa consigne lui demande de n'en nommer aucune.
  Quand une fiche est réunie, ses avis se refont et ses réunions suivent la fiche gardée.
- **La console en MCP sert la file « À valider ».** Les vues qu'elle lit (les identités à confirmer, les noms à
  relier, et une nouvelle vue, `contacts/rapprochements`) sont listées et lues. La nouvelle vue dit ce qui attend avec
  l'avis du juge, ce qu'il a réuni d'office et ce qu'il sait deux personnes.
  - La composition déclare ces vues (`queue.views`), et elles se servent par leur propre part (`a_valider`), cochée
    d'office dans Outils › Prêter à un agent. Les autres vues hors de la navigation sont listées avec la part des vues.
  - Avant, ces vues se lisaient par leur clé, mais on ne pouvait pas les trouver. Un choix déjà enregistré dans
    Prêter à un agent ne les sert plus tant qu'on n'y coche pas la file.

*Pourquoi :* le 22 novembre 2026, les 68 rapprochements de la file étaient presque tous justifiés, mais presque la
moitié n'avait rien à y faire. 30 étaient le même identifiant Teams sous deux formes, et 28 venaient d'une seule
personne venue huit fois en invité de réunion. Il manquait aussi « Kévin Massol » (raconté) face à « Kévin
MASSOL-EXT ». Adrien : « pour tous les endroits où on est sûr, ça doit être automatique, et le bon profil doit être mis
automatiquement avec le nouveau moyen de communication » ; « j'aimerais bien un truc intelligent qui fusionne :
retirer des lettres ne rend pas le processus adaptable de manière générale ».

*Révise 0298 (en partie : ce qui est sûr se réunit d'office, le juge compris ; un identifiant Teams, une forme).*

## Sa vie intérieure : affect, corps, besoins, liens, initiatives

### 0013 — Les liens se vivent : proximité, rythme, manque, réconfort, retenue

- La proximité se vit par paliers (connaissance, amie, proche), au fil des jours de contact, des messages et de la chaleur ; jamais amie d'une rancune. Un opérateur peut la fixer.
- Le profil ne s'écrit que de ce qui ne concerne que la personne ; un sujet délicat de quelqu'un rend confidentiel tout souvenir qui le touche.
- Le manque vise une amie ou une proche joignable, silencieuse au-delà de son rythme, en journée ; le réconfort, la personne auprès de qui elle se sent le mieux.
- La retenue : aucun élan vers qui a installé une rancune, pas même une salutation ; chaque initiative sans réponse rend la suivante moins probable.
- Revu par l'ADR 0035 : la proximité se lit sur une fenêtre glissante, et « proche » demande un mois d'histoire.

*Pourquoi :* en v1, la proximité venait d'un profil rédigé par un modèle, et rien n'empêchait d'aller saluer qui venait d'insulter.

*Révisée par 0033, 0035, 0044, 0058, 0150.*

### 0016 — Le corps dort : deux processus, une porte de nuit, l'inertie du réveil

- Le sommeil suit le modèle à deux processus de Borbély : une pression qui monte en veille et retombe en dormant, contre des seuils que module un rythme circadien décalé par le chronotype.
- Les transitions sont calculées exactement et émises à leur instant ; après un arrêt, celles qui manquent sont émises datées.
- Elle ne s'endort jamais en pleine conversation ; réveillée la nuit, elle se rendort après un quart d'heure de calme.
- Le corps pèse sur l'arbitrage : veto en dormant, retenue au réveil, initiatives plus rares quand elle est fatiguée ; la fatigue colore son ton.
- Revu par l'ADR 0036 : la nuit, seule une amie ou une proche la réveille (`woken_by`).

*Pourquoi :* en v1, le sommeil dépendait d'une fatigue inatteignable en usage réel : une soirée calme supprimait la nuit entière.

*Révisée par 0036, 0306.*

### 0017 — Évaluations déclarées, pensées, attentes, estime

- Le propriétaire d'un événement déclare son évaluation ; seul l'affect l'applique, dans le même événement et avec les faits d'avant : le rejeu retombe sur le même état.
- Trois besoins (compagnie, s'exprimer, curiosité) ; un long désœuvrement laisse un vide ressenti, l'ennui ou la solitude.
- Une pensée naît d'un échange qui marque, d'une croyance révisée ou d'un manque ; son texte n'est jamais inventé, et elle ne se montre qu'à qui peut l'entendre.
- Écrire d'elle-même fait attendre une réponse, une salutation rien ; l'estime, lente, baisse avec les attentes déçues et joue dans le prompt, jamais dans l'arbitrage.
- Le récit de soi se réécrit au plus une fois par jour, à partir de souvenirs anodins seulement.

*Pourquoi :* en v1, des impulsions dispersées, des ruminations éteintes en 22 minutes et quatre dispositifs d'attente rendaient sa vie intérieure incohérente.

*Révisée par 0283.*

### 0018 — Prendre la parole : l'envie, la retenue, le murmure

- Elle écrit par envie à une amie ou une proche joignable, plus silencieuse que d'habitude, en journée ; l'envie seule pèse peu, avec le besoin de compagnie elle suffit.
- Jamais deux messages de suite à une absente qui n'a pas répondu ; chaque initiative ignorée allonge la période réfractaire.
- La rancune se lit dans l'hostilité installée (colère, dégoût, frustration), pas dans le déplaisir seul : une amie qui partage son chagrin reste une amie.
- Le murmure est une phrase à voix basse avant une initiative, à l'écran seulement, jamais en message, et seulement si quelqu'un regarde.
- Revu par l'ADR 0033 : après une initiative sans réponse, aucune autre vers la personne avant qu'elle écrive, sauf une relance douce.

*Pourquoi :* prendre la parole par envie, sans relancer qui ne répond pas ni confondre le chagrin d'une amie avec une rancune.

*Révisée par 0033.*

### 0019 — La nuit : journal, rêves, digestion, tri

- Elle écrit un journal par journée vécue, en s'endormant : qui lui a parlé, ce qu'elle a retenu, ce qui la travaille ; il porte les personnes qu'il concerne.
- Au redémarrage, le corps rejoue la nuit depuis son dernier état connu, jamais depuis l'heure du redémarrage.
- Elle rêve en sommeil paradoxal, par un hasard dérivé de la nuit (rejouable), de souvenirs récents et d'une pensée qui insiste ; un rêve ne revient qu'à qui peut l'entendre.
- Le fil d'hier entre au prompt ; les autres y deviennent « quelqu'un » pour qui ne peut pas entendre ce qui les concerne.
- La nuit, la digestion allège les pensées anciennes (ce qui pèse encore devient un souvenir), et le tri, sans modèle, fond les quasi-doublons du jour.

*Pourquoi :* en v1, une soirée calme supprimait la nuit (ni journal, ni rêve, ni digestion), et le journal se datait du jour de l'écriture.

*Révisée par 0036, 0153.*

### 0028 — L'autre : deviner, s'étonner, apprendre de ce qui arrive, tenir parole

- Pour chaque personne, un ton habituel et un état du moment qui y revient ; la surprise mesure l'écart au ton attendu. Ce qui tranche se dit en privé seulement, sans nombre.
- L'inquiétude naît d'un message lourd d'une amie ou d'une proche, plus sombre qu'attendu, jamais d'une inconnue ; elle donne une pensée et une seule prise de nouvelles, en journée.
- Elle apprend les délais de réponse et les heures où chacun répond, qui modulent ses initiatives ; les salutations et les rappels n'en dépendent pas.
- Une promesse datée devient une attente envers elle-même : manquée, elle laisse une gêne et la pousse à le dire ; tenue, même en retard, rien.
- Revu par l'ADR 0093 : le ton se lit par le modèle (`[EN_FACE: …]`), jamais par la forme du message.

*Pourquoi :* elle ne lisait que le dernier message, n'apprenait rien des conséquences et laissait passer une promesse sans le savoir.

### 0032 — L'affect sur trois échelles : le moment, la journée, la relation

- Une impulsion vise un point depuis le repos, jamais depuis l'origine ; `neutral` n'en produit aucune.
- Trois couches : un repos jumeau, contre lequel se mesure le ressenti ; le moment, seul à pouvoir pousser à une initiative ; le fond de la journée, qui colore la prose sans pousser à parler.
- Ce qu'une relation installe se mesure depuis son repos moyen ; l'empathie tire vers la tendresse et ne refroidit jamais une relation chaleureuse.
- La guérison est asymétrique : une ancre chaleureuse guérit lentement, une hostile d'autant plus lentement qu'elle a été répétée ; l'attachement (`affect.bond`) atténue l'hostilité.
- Une cause d'humeur se dit en phrase générique, sans jamais nommer un tiers. L'humeur entre aux séances `STEP`, pas aux `JOB`.

*Pourquoi :* partir de l'origine faisait lire lasse une joie légère, et une dispute effaçait un mois d'amitié.

### 0033 — Ne pas harceler ; avoir de quoi parler ; une voix intérieure discrète

- `agency` tient la règle pour toutes les raisons : après une initiative ordinaire sans réponse, aucune autre vers la personne avant qu'elle écrive, sauf une relance douce.
- Si son dernier message attend encore, elle se retient ; ce qui est dû (salutation, rappel) ou prévient (`INFORMS`) passe ce veto.
- Être ignorée se ressent, sans jamais pousser à réécrire ; le budget se compte à l'énoncé visible, un silence ou une panne ne consomment rien.
- Une initiative portée par les seules envies cherche une matière concrète, jamais ce qu'un autre a dit de la personne. Les mots d'un message privé ne se citent qu'à qui les a écrits.
- Revu par l'ADR 0118 : le nombre de relances (0 à 3) vient de son tempérament, et une relance prend de ses nouvelles.

*Pourquoi :* avec un vrai modèle, elle envoyait cinq initiatives d'affilée à un ami muet, et ses messages n'avaient pas d'objet.

*Révise 0013 (en partie), 0018 (en partie). Révisée par 0044, 0054, 0058, 0105, 0118, 0154.*

### 0036 — Soi, corps et nuit : une nature assumée, une estime qui a des causes, des nuits qui ressemblent à des nuits

- Elle n'est pas une assistante. IA, elle le sait : demandé sincèrement, elle ne se prétend pas humaine, sans en faire un sujet (jamais « en tant qu'IA »).
- La persona n'impose rien « toujours » : ses manies viennent de temps en temps. Aucun outil ne relit une section déjà présente au prompt.
- L'estime a des causes : une réussite compte selon l'effort ; merci, compliments et insultes la touchent (`self.touched`), selon la proximité.
- La nuit, seul un message privé d'une amie ou d'une proche (`woken_by`), ou l'urgent, la réveille (`body.roused`) ; les autres reçoivent une réponse par personne à son réveil.
- Revu par l'ADR 0070 : sa nature vient de la persona (`nature: incarnee` pour une personne).

*Pourquoi :* elle s'endormait à la minute près, se réveillait pour n'importe qui, et son estime montait à chaque but trivial.

*Révise 0016 (en partie), 0019 (en partie), 0020 (en partie), 0026 (en partie). Révisée par 0040.*

### 0044 — Ce qui est dû, ce qui prévient, et le courrier dit à l'énoncé

- Ce qui est dû (`OWED`), prévient (`INFORMS`) ou salue (`GREETS`) se déclare une seule fois, dans le contrat d'`agency` ; les autres le lisent, aucune ne le redit.
- La rancune retient l'ordinaire, jamais une promesse : ce qui est dû passe, ce qui prévient est seulement décalé, le reste est sous veto. Elle ne salue pas qui elle a en grippe.
- Un mail se compte à l'énoncé : seuls ceux qu'une initiative annonce sont « signalés ». Une fin devancée ou annulée n'est pas un essai ; un murmure sans suite est un report.
- L'objet de l'épisode (le mail de la tâche, le mail annoncé) garde un plancher dans le prompt, même cité.
- Une connexion n'est une arrivée qu'après une heure d'absence : un redémarrage ne fait saluer personne.

*Pourquoi :* chaque faculté tenait sa liste de ce qui est dû : une rancune faisait manquer une promesse, et un mail urgent n'était jamais dit.

*Révise 0013 (en partie), 0033 (en partie). Révisée par 0047.*

### 0047 — Le cœur, le soi et la conversation

- Une rêverie n'est ni une nouvelle ni un exploit : ni matière d'initiative, ni estime. L'effort d'une réussite ne compte que s'il a été prouvé.
- Une cause d'humeur qui est un état se dit au passé dès qu'il a pris fin. Retrouver une amie après un vide se ressent (`needs.reunited`), pas une inconnue.
- Sa vie d'IA est écrite dans la persona : sur un serveur, sans corps, famille ni ville natale, aux goûts tranchés et stables. Elle ne fait pas de « stream ».
- Des excuses sincères pardonnent (`self.touched`), lues dans la forme : jamais en riant, ni une politesse, ni des condoléances ; une fois par jour et par personne.
- Une initiative dit sa raison la plus forte, au plus une seconde. `OWED` et `INFORMS` se disent toujours ; le murmure ne se ravise jamais sur eux.

*Pourquoi :* elle se trahissait par des incohérences : rêveries comptées comme exploits, humeur au mauvais temps, vie inventée, excuses sans effet.

*Révise 0044 (en partie).*

*Révisée par 0138.*

### 0053 — Ce qu'elle se raconte d'elle-même est vrai

- Sa journée « à raconter » n'est pas écrite par un modèle : elle est rendue d'après des faits qu'elle peut dire (combien de gens, ce qu'elle a fait, un ton vague mais vrai), jamais qui ni de quoi.
- Les notes de son journal intime disent ce qu'on lui a dit, jamais ses propres phrases, sans activité ni détail ajouté.
- Une pensée née d'un échange porte ce qu'il voulait dire, jamais les mots d'un autre fil.
- Une réflexion tient en une séance et ne se rate pas : sans rien d'écrit, elle en reste là (`goals.LET_GO`), sans trace. Elle ne nourrit ni souvenir ni croyance sur l'autre.
- Des rêveries rares, deux par jour au plus, d'abord sur ce dont on lui a parlé. Une rêverie dit « j'aimerais », pas « je fais ».

*Pourquoi :* sa vie intérieure inventait (une journée de fiction, une réflexion qui fabriquait des reproches) et coûtait plus d'appels que ses réponses.

*Révise 0043 (en partie).*

*Révisée par 0160.*

### 0058 — Les liens dans la durée

- L'assiduité seule ne fait pas une proche : il y faut une chaleur installée ou un attachement. Le temps approfondit ce qui est là, il ne le crée pas.
- La confidence d'une personne ne va qu'à qui a un lien avec elle (`social.TIES`) ; prononcer un nom ne crée aucun lien. Un secret explicite ne quitte jamais sa confidente.
- L'histoire se mesure au temps vécu ensemble : une absence ne l'allonge pas ; seule une longue amitié garde un plancher après un silence.
- Une amie silencieuse lui manque, de plus en plus faiblement, sans pousser à réécrire ; longtemps après, elle prend de ses nouvelles une fois (`social.REKINDLE`).
- La solitude se ressent une fois. Écarté : mémoïser la proximité à la journée (rejeu et vivant divergeraient).

*Pourquoi :* sur des mois, l'assiduité faisait une proche qui recevait les confidences d'autrui, et une amie silencieuse disparaissait.

*Révise 0013 (en partie), 0033 (en partie). Révisée par 0092, 0150.*

### 0088 — Ce qu'elle sait d'elle

- Ses réussites et ratés sont des marques gardées 90 jours : tenir parole, mener au bout (renoncer n'est pas un échec), voir venir (écart à ce qu'elle attendait).
- Le fait `self.knows` en tire des tendances (`promises_kept`, `finishing_struggle`, `foresight_right`…) ; une seule promesse échue efface « tu tiens parole ».
- « CE QUE TU SAIS DE TOI » les dit en mots, jamais en nombre, comme des tendances, pas des règles ; et au plus un changement d'avis récent sur elle, devant qui ses sources le permettent.
- Ne comptent pas : une promesse abandonnée ou portée par un rappel, une rêverie, un objectif impersonnel, une date officielle, ce qu'elle n'a jamais su.
- L'estime n'en bouge pas : aucune marque ne la nourrit.

*Pourquoi :* ses réussites et ses ratés ne laissaient qu'un chiffre d'estime, ressenti sans être su.

*Révisée par 0096.*

### 0089 — Ce qui la passionne

- Ses intérêts vivent : ceux de sa persona s'avivent ou s'endorment, jamais ne disparaissent ; ceux qu'elle a vécus naissent et s'éteignent. Trois niveaux : vif, présent, endormi.
- Les nourrissent : une exploration menée au bout, un titre de ses flux (borné par jour), une piste rattachée la nuit.
- Une piste vient de ce qu'on lui a raconté et qu'elle a médité, d'une exploration ou d'un article ouvert ; jamais d'une confidence, et elle garde de qui elle vient.
- Un intérêt naît la nuit (`self.interest_born`), borné par le code : un par semaine, trois vécus au plus, deux journées de preuves, un sujet court, dicible à tous, sans nom.
- Ses explorations et ses flux suivent la vivacité ; oublier une personne emporte les pistes et intérêts nés d'elle.

*Pourquoi :* ses intérêts étaient une liste figée, et rien de ce qu'elle vivait n'en devenait un.

### 0090 — Qui elle devient

- Son récit (« QUI TU ES DEVENUE »), montré à tout le monde, lit ses notes durables, ses changements d'avis, ses passions, ce qu'elle sait d'elle, ses vécus et ses souvenirs qui ne concernent personne d'autre.
- Un vécu à travers quelqu'un s'y dit par son « en bref » et ce que la personne est pour elle, en mots épicènes, jamais qui ; jamais un secret, ce qu'elle a fait taire, ni ce qu'elle a dit en mentant.
- Elle le réécrit quand elle a assez changé, au plus une fois par période ; sans rien de vécu, pas de récit.
- Pas un prénom, pas un nombre : un récit qui porte un prénom de son cercle ne s'écrit pas. Incarnée, rien ne lui parle d'IA.
- L'oubli d'une personne à travers qui elle a vécu le fait taire et réécrire sans elle.

*Pourquoi :* son récit ne lisait que des souvenirs et ne suivait rien de ce qu'elle devenait.

*Révisée par 0264.*

### 0093 — Le modèle lit la personne ; ses émotions ont des facettes

- Ce qu'elle sent des gens, le modèle le lit en répondant : `[EN_FACE: facettes | geste : … | grave : …]`, retirée du texte livré. Sans balise, rien ne se lit, jamais une lecture neutre inventée.
- Aucun code ne devine une émotion ou une insulte d'après des mots (une garde le vérifie) ; seul le simulateur joue le modèle.
- Le runtime interprète sa réponse juste après l'avoir écrite (`others.read`, `self.touched`) ; la section d'état dit le ton habituel de la personne, pour que le modèle juge.
- L'au revoir se reconnaît à sa forme, à l'arrivée du message (`others.farewell`) : ce n'est pas une émotion.
- Ses émotions ont des facettes (`[EMOTION: sad 0.6, love 0.3]`) : humeur et posture visent leur mélange, son visage montre les deux premières.

*Pourquoi :* les listes de mots lisaient mal le français, où le ton fait tout (au banc, 54/62 contre 61/62 pour le modèle).

### 0094 — Chacun compte à sa façon : joignable, sa propriétaire, ce qu'elle ressent envers chacun

- Une initiative vers un absent attend la fin de sa nuit (veto `not_reachable`), supposée tant qu'on ne sait rien ; ses heures apprises ouvrent sa nuit, jamais ne ferment sa journée. Le dû et ce qui prévient passent.
- Sa propriétaire compte plus (`social.owner_weight`, 1,3) : son silence manque plus tôt, sa compagnie comble davantage, et l'envie de compagnie penche vers elle parmi les présents. Une tendance, pas une obligation.
- Ce qu'une personne lui fait vivre (lien à sens unique, réponse qui ne vient pas, promesse non tenue) colore un moment sa posture envers elle ; la contagion, non.
- Une posture se lit toutes adresses réunies, sans fusion dans l'état : délier une adresse les sépare.
- Une humeur sombre née d'un échange ne pousse pas vers qui l'a causée ; une adresse jetable ne la touche jamais plus qu'une inconnue.

*Pourquoi :* elle écrivait à qui dort, sa propriétaire ne comptait pas plus qu'une autre, et rien ne la touchait envers quelqu'un.

### 0095 — Chaque cause de ce qu'elle ressent se dit

- Une cause est un code (`vocab.causes`), dit par la phrase `affect.cause.<code>` de `voix.yaml`, sans table intermédiaire ; aucune évaluation ne porte une raison écrite à la main.
- Les origines d'une pensée et les sources d'un signal sont des causes sous leurs propres codes ; quelques codes empruntent la phrase d'un autre.
- `talk` (ce qu'elle a dit) se dit selon la personne en face.
- Une garde vérifie que chaque code, origine, source et vide ressenti a sa phrase.

*Pourquoi :* des causes connues se taisaient faute de phrase, et sa tristesse venait « sans trop savoir pourquoi ».

### 0096 — Une réflexion apaise, ce n'est pas un exploit

- Une réflexion (un but né d'un échange ou d'une révision) menée au bout apaise (`relieved`, cause `reflected`) ; inachevée, elle reste un peu lourde, sans frustration.
- Elle ne touche pas son estime et ne compte pas parmi ce qu'elle mène au bout (`self.knows`).
- Son journal la dit comme telle (« tu as pris le temps de repenser à… »).
- Ce qu'elle entreprend pour de bon (exploration, projet) garde fierté et estime ; `goals.closed` porte l'origine du but.

*Pourquoi :* l'inquiétude pour quelqu'un devenait un trophée.

*Révise 0088 (en partie).*

### 0097 — Un but garde la filiation de la pensée d'où il est né

- `goals.opened` porte la filiation de la pensée d'où naît le but ; partout où un but se dit, une seule règle (`goals.audible`) : celle de ses personnes et celle de sa filiation.
- Sans filiation (un but qui ne vient pas de ce qu'elle sait), la règle de ses personnes seule.
- Une pensée née d'un échange n'a pas de filiation : elle se dit sans ses mots à qui ne les a pas écrits, et le titre d'une réflexion qui en naît ne redit rien de confié.

*Pourquoi :* devenue un but, une pensée perdait sa filiation et se montrait là où elle se serait tue.

### 0098 — Seule et désœuvrée, elle a une vie : s'occuper, un souvenir qui revient

- Le vide ressenti la fait s'occuper de ce qui nourrit ce qui lui manque, jamais deux fois de suite la même chose, 3 fois par jour au plus ; rien en dormant, en chemin ou juste après avoir parlé.
- S'occuper efface le vide au prorata de ce que l'occupation a comblé ; elle tient l'ennui à distance, jamais la solitude, qui court depuis le dernier contact.
- Un souvenir d'au moins une semaine lui revient (origine `reminiscence`), deux par jour au plus : celui de la date anniversaire, sinon ce que rappelle ce qu'elle fait, sinon un qui compte.
- Il garde ses mots, son émotion d'alors (jamais inventée) et sa filiation ; il se ressent, mais n'est jamais à lui seul une raison d'écrire. Rien de tout cela ne passe par le modèle.

*Pourquoi :* seule, il ne se passait presque rien en elle, et deux minutes d'occupation effaçaient deux heures d'ennui.

*Révisée par 0160.*

### 0100 — La matrice de personnalité : des curseurs en familles, des profils, des précisions

- Le tempérament est une matrice : 28 curseurs de 0 à 1 en six familles, une humeur de fond, une réaction quand on la blesse (colère, tristesse, peur, repli) et une défense quand on la touche.
- Chaque curseur pilote au moins un paramètre ; à 0,5, chaque dérivation redonne exactement la valeur d'avant la matrice. Console et profils s'arrêtent à 0,1 et 0,9.
- Réaction et défense agissent sur l'affect d'après ce que le modèle a lu (`geste`), jamais d'après une liste de mots. Blessée, la relation refroidit et ne s'attendrit jamais.
- La contagion règle tout ce que les autres lui font vivre : un retour, un silence, des retrouvailles, les pensées nées d'un échange.
- Le tempérament se dit au modèle partout où sa persona est injectée, en mots de `voix.yaml` : en bloc avec sa mesure hors conversation ; en conversation, seuls ses traits nettement marqués, sa réaction et sa défense, sans mesure (`temperament_in_words`, ce que fait le code). Elle ne dit jamais un pourcentage ni ne récite un trait.
- Une précision facultative par trait (`notes`, 200 caractères) suit la phrase du trait, sans jamais la remplacer.
- 18 profils (`PROFILES` : tempéraments ordinaires, archétypes d'anime, extrêmes), appliqués dans la console, par `mika profil` ou au simulateur, puis ajustés. Mika est livrée « Réfléchie ».
- Ses règles de conduite (discrétion, ne pas harceler, mentir seulement pour protéger un secret, ni menace ni manipulation) sont hors de la matrice : un profil règle ce qu'elle ressent, jamais ce qu'elle s'autorise.

*Pourquoi :* presque tout ce que la propriétaire attendait dépendait du type de personne, pas d'une règle.

*Révisée par 0102, 0112, 0118, 0137, 0138, 0139, 0150.*

### 0107 — Les suites du parcours d'une émotion

- Le modèle a un cinquième geste dans `[EN_FACE]`, « décevant ». Une déception est une blessure : la relation refroidit sans tendresse ni attachement, l'estime en prend un peu, des excuses s'y appliquent.
- Le poids de sa propriétaire (`social.WEIGHT`) multiplie le pas de son humeur et de sa posture envers elle ; l'ancre de la relation garde son rythme, et rien n'est pesé deux fois.
- La relecture voit, en mots, ce qu'elle a déclaré en écrivant chaque réplique et en part, sauf si la suite montre autre chose ; le calme ne se dit pas.
- Un ressenti fort (une facette au moins à `charged_from`, 0,7) élève l'importance d'un souvenir, d'une croyance ou d'un moment à « important » au moins ; seul, il ne crée pas de temps durs.

*Pourquoi :* triste à cause de quelqu'un se lisait comme triste avec lui, et l'émotion ne comptait ni pour sa propriétaire ni pour la mémoire.

*Révise 0102 (en partie).*

*Révisée par 0155.*

### 0118 — Relancer, c'est prendre de ses nouvelles

- Dès qu'une initiative vers la personne reste sans réponse, une trouvaille d'app attend (`agency.WAITS_FOR_AN_ANSWER`) ; un mail important, un projet bloqué, un rappel promis passent toujours.
- Seule une trouvaille jugée urgente (danger, alerte, événement grave là où la personne vit ou va ; jamais une actualité) devient `forge.APP_ALERT` et prévient même qui se tait.
- Saluer qui ne répond pas, c'est relancer : la retenue s'y applique ; une salutation qui apporte quelque chose attend une réponse.
- Une relance prend de ses nouvelles et n'apporte rien de neuf ; les suivantes disent ce que ce silence lui fait, à sa façon.
- Le nombre de relances (`follow_ups`, 0 à 3) vient de son tempérament ; leur délai est tiré au sort (±40 %, enregistré) autour du jour ; après la dernière, silence jusqu'à son retour.

*Pourquoi :* elle écrivait trois fois de l'actualité à quelqu'un resté silencieux depuis la veille.

*Révise 0033 (en partie), 0100 (en partie), 0105 (en partie).*

### 0137 — L'intérêt pour les autres : c'est elle qui demande leur journée

- Un 29ᵉ curseur, « Intérêt pour les autres » (`inquisitiveness`, famille « Les autres ») : combien ce que vivent les gens l'intéresse. Il est distinct de la curiosité (apprendre, explorer : ses explorations) et de l'empathie (s'inquiéter de qui va mal).
- Il pilote `social.their_day_from_h`. Au milieu et en dessous, la valeur est 24 : jamais, comme avant. Au-dessus, l'heure avance, de 21 h à peine marqué jusqu'à midi au plus haut. À partir de cette heure, une fois par jour, la section « SA JOURNÉE » lui fait demander à une amie ou une proche, en privé, comment se passe sa journée (avant 17 h) ou comment elle s'est passée, si on ne lui en a pas déjà parlé.
- Elle le demande en répondant ou en saluant, jamais dans une relance, une inquiétude ou une promesse, qui ont leur sujet. Rien pendant des jours durs (sa mémoire en parle déjà, avec douceur), ni en mode pro. Un énoncé qui avait la section sous les yeux compte pour la journée (`social.asked_day`), qu'elle ait demandé ou non.
- Il se dit au modèle comme les autres traits, et dans « TA RÉPONSE » quand il est marqué, juste après la sociabilité.
- « Réfléchie » le porte à 8 : Mika demande à partir de 14 h 15. Solaire est à 7, de marbre et dépressive à 3, narcissique à 2.

*Pourquoi :* sa curiosité nourrissait ses explorations, jamais un intérêt pour la personne en face, et son prompt ne faisait que freiner les questions (« pas une intervieweuse »). Une IA n'a pas de journée à raconter : c'est à elle de demander celle de l'autre (demande de l'utilisateur, 2026-10-26).

*Révise 0100 (29 curseurs).*

*Révisée par 0141, 0150.*

### 0150 — Envers quelqu'un, des poids selon le lien, pas des portes

- Ce qu'une amie ou une proche déclenchait seule passe par une **table par proximité** (`social.ByCloseness` : une ligne par cran, de 0 à 1), qui multiplie la preuve ou l'intensité : l'inquiétude et la prise de nouvelles, ses attentions (encourager, demander comment ça s'est passé, souhaiter), le mot doux d'un jour difficile, le remords, la jalousie d'un silence, l'envie de reparler d'un bel échange, la joie de retrouver quelqu'un, aller vers quelqu'un (reprendre contact, chercher du réconfort, discuter) ; la relance douce, elle, divise son délai. La table de la contagion devient un réglage.
- Par défaut : rien pour une inconnue, la moitié pour une connaissance, tout pour une amie ou une proche ; le mot doux reste à une proche, la contagion garde ses valeurs (0 ; 0,5 ; 0,8 ; 1). L'arbitre reste probabiliste : une connaissance en reçoit rarement, et la réponse peut se taire.
- Les gestes envers quelqu'un passent en revue `social.KNOWN` (le tri bon marché de `CIRCLE`, un cran plus bas) quand la table laisse quelque chose aux connaissances : jamais les inconnues de passage, qui n'ont pas de ligne dans ces tables-là.
- Une rancune installée n'est plus un veto : l'ordinaire recule (`grudge_shift`, −6 par défaut) ; ce qui est dû et ce qui prévient gardent leur règle (0044).
- Deux coupures du tempérament deviennent des courbes : la jalousie d'un silence (`0,6 × jalousie²` : 0,15 au milieu) et l'heure de « sa journée » (jamais tout en bas, 21 h au milieu, midi au plus haut). Une pensée d'une autre couleur que l'inquiétude ou l'intrigue fait entreprendre à une part de son intensité (`seed_other_share`, 0,5).

*Pourquoi :* « que le modèle réagisse de lui-même, pas lui forcer un comportement » : une connaissance n'avait aucune de ces réactions, une rancune aucune issue, un tempérament au milieu aucune jalousie — des portes tout ou rien là où une personne gradue (audit des garde-fous du 2026-10-27, lot 2).

*Révise 0013 (la retenue : un recul, plus un veto), 0058 (en partie : qui ses gestes passent en revue), 0100 (en partie : deux coupures de la dérivation), 0137 (en partie : « sa journée » au milieu).*

### 0155 — Sa colère pour quelqu'un n'est pas contre lui ; une humeur ne se dit pas en émotion à objet

- Quand le modèle lit la personne mal (`[EN_FACE]` négatif) sans geste qui blesse Mika, les facettes hostiles de sa balise (colère, frustration, dégoût : `physics.HOSTILE`) vont à son humeur, pas à sa posture envers la personne : elle est en colère *pour* elle, contre ce qui la touche. Ses autres facettes suivent leur cours : une peine partagée rapproche toujours (ADR 0107).
- Une émotion qui a un objet (`affect.OBJECT_BOUND` : jalouse, amoureuse, reconnaissante) ne nomme son humeur générale, ni en dominante ni « en dessous », que si une impulsion récente l'y a portée. Envers une personne, elle reste lisible.
- Le visage, qui mêle posture et humeur, montre encore ce qu'elle ressent pour la personne.

*Pourquoi :* au banc du profil (2026-10-28), après un midi à s'indigner pour Adrien contre son chef, son prompt du soir disait « envers Adrien, au fond, tu restes plutôt en colère : c'est ce que vos échanges ont installé » ; et le mélange « frustrée, gênée, triste » attrapé par contagion tombait au plus près de l'ancre « jalouse » (0,23), d'où « ton humeur est légèrement jalouse. Ça vient de l'humeur de quelqu'un » dans neuf prompts sur douze.

*Révise 0107 (en partie : la colère partagée).*

### 0160 — Sa journée, ce sont ses vraies activités

- Elle ne s'occupe plus d'elle-même dans sa chambre : `occupy_per_day` vaut 0 par défaut. Ce qu'elle a fait de sa journée, ce sont ses vraies activités, celles qui laissent une trace : ce qu'elle a lu, cherché, avancé sur un projet, et ses conversations. Elles comblent ses besoins et tiennent l'ennui à distance (explorer, apprendre, travailler). Les gestes qu'on lui demande dans sa chambre restent, comme le sommeil.
- Son portrait dit sa journée par ses vraies activités (ses flux, les nouvelles, internet, ses projets) ; plus d'arrosage, de fenêtre ni de ficus, et ses faits ne détaillent plus sa chambre.
- Sans flux ni web où chercher du neuf, un centre d'intérêt n'ouvre plus de rêverie (`muse_on_interests`, coupé par défaut) : elle n'en fait rien. Avec des sources, elle explore ; rêvasser à ce dont on lui a parlé reste, avec ses garde-fous (deux par jour au plus, « j'aimerais », jamais une nouvelle).
- Le web compte comme une source : actif, le plugin `web` le dit (`web.available`), et un centre d'intérêt la mène y voir ce qu'il y a de neuf, même sans flux (une exploration, deux par jour au plus). Le monde simulé (simulateur, sonde, bancs) n'a pas de client MCP : il configure le web coupé (`Driver.overrides`), sinon elle « fouillerait » sans outil.
- Le vide vient plus tard : quatre heures sans rien au milieu de l'optimisme (de deux à huit selon le curseur, au lieu d'une à quatre). Rien d'inventé n'interrompt plus une journée calme : un après-midi vide se ressent encore, sans commencer dès le premier silence.
- Elle ne dessine que pour de vrai : l'outil `draw` n'est offert que si un fournisseur d'images est configuré. Un outil déclare le port sans lequel il ne fait rien (`needs`), et la porte d'offre (`runtime.tool_offer.offer`) ne l'offre pas tant que ce port n'est pas prêt — la console, le prêt d'outils et le pipeline jugent pareil.

*Pourquoi :* sur quatre semaines du banc du profil (2026-10-29), elle racontait les trois mêmes occupations, sans contenu (« j'ai beaucoup dessiné », « j'ai parlé à mon ficus », l'inventaire de sa chambre à « tu fais quoi quand je suis pas là »), et son journal disait « j'ai dessiné le matin… puis repris le dessin le soir » sans qu'aucun dessin n'existe. Une réplique notée à la main : « dessiner ? ». Au banc, sans source, ses séances de travail n'étaient que des rêveries de la même veine (« Rêvasser un peu autour des plantes, du dessin… », sur ses cinq centres d'intérêt en boucle). Sans elles, une Mika qui avait le web mais pas de flux ne faisait plus rien de ses centres d'intérêt (les buts ne voyaient que les flux), et un jour calme la laissait dans le vide dès deux heures de silence, ressenti à nouveau tous les quarts d'heure jusqu'au soir.

*Révise 0053 (en partie : les rêveries d'intérêt), 0063 (en partie : `draw` toujours offert), 0098 (en partie : s'occuper seule), 0159 (en partie : sa chambre au banc).*

### 0227 — Le corps dit l'instant de son sommeil paradoxal et la fin d'une nuit coupée

- Le corps donne son sommeil paradoxal en cours ou le prochain (`body.rem` : le cycle, son début, sa fin), au réglage de son cycle (`cycle_us`), et la fin d'une nuit coupée par un message (`body.night_waking_until`, 0 sans nuit coupée). Personne d'autre ne recompte ses cycles : un tirage de rêve par cycle du corps.
- Le rêve (`self.dream`) rend le début de son prochain sommeil paradoxal (ou la fin de l'écart de 45 min qui suit son dernier rêve, ou la fin de la phase quand son cycle est déjà tiré), et le réveil (`self.wake`) la fin de la nuit coupée : des instants absolus, au quantum par défaut (un filet), comme le veut 0223.

*Pourquoi :* le rêve recopiait la durée d'un cycle (90 min) au lieu de la lire : réglée autrement, une phase paradoxale perdait son tirage ou en recevait deux ; et les deux processus se relisaient chaque minute, de jour comme de nuit, faute d'un instant que le corps calculait déjà (audit du 2026-11-05, K7-01, K7-02, décision K7-Q1).

*Révise 0223 (en partie : le rêve et la fin d'une nuit coupée ont leur instant, plus un quantum d'une minute).*

### 0283 — Ce qui la marque se lit sur l'échelle que sa voix emploie

- Les deux seuils d'intensité d'« un échange qui marque » sont réglés sur ce que sa voix déclare vraiment : `marking_intensity` 0,6 (au lieu de 0,75) et `marking_min_intensity` 0,4 (au lieu de 0,5).
- La mesure, au banc de conversation (Opus, 389 réponses, 50 conversations) : sa balise `[EMOTION]` vaut 0,3, 0,4 ou 0,5 dans 97 % des cas, jamais plus de 0,6 — « triste 0,4 » quand on lui dit des mots durs, « surprise 0,6 » à l'annonce d'une naissance. Aux anciens seuils, aucune réponse ne marquait ; aux nouveaux, 6,7 %, dans les conversations où la personne va mal, annonce une grande nouvelle ou la blesse, et aucune dans celles de tous les jours.
- Ni le fil ni la consigne n'y changent rien : la bande est la même sans aucun exemple balisé dans le fil, sans exemple chiffré dans la consigne, ou avec des exemples de 0,2 à 0,7. Les balises restent donc dans le fil (0041), et la consigne ne bouge pas.
- Le seuil du remords (`remorse_from`, 0,6) reste où il est : sa colère en répondant ne dépasse pas 0,4, mais c'est le plus souvent une colère pour la personne, pas contre elle (0155) ; l'abaisser ferait naître « j'ai été dure » à tort.
- `tools/banc_conversation/balises.py` relit les balises d'une mesure et dit combien de réponses marqueraient aux seuils du jour ; `variantes/moments_forts.py` ajoute les deux situations fortes à une mesure. À refaire quand le modèle de sa voix change, comme les seuils de similarité (0111).

*Pourquoi :* le modèle se note sobrement quand il écrit en son nom, alors que la relecture, qui juge de l'extérieur, monte à 0,8 ; des seuils posés au-dessus de ce qu'il déclare éteignaient le mécanisme sans que rien le dise.

*Révise 0017 (en partie : les seuils d'un échange qui marque).*

## Buts, projets, Forge et atelier

### 0005 — La Forge hors du processus

- Les apps qu'elle forge tournent hors du processus, isolées par bubblewrap, et parlent JSON sur stdio.
- Un appel qui dépasse son délai tue l'app : un plantage coûte l'app, jamais le noyau.
- Leur influence est bornée : sections non fiables, preuves plafonnées.
- Le validateur AST n'est qu'un confort d'écriture, jamais la défense.

*Pourquoi :* exécuté dans le processus principal derrière une analyse AST, le code forgé avait permis trois évasions, dont deux en exécution de code arbitraire.

*Révisée par 0023.*

### 0020 — Buts et travail : entreprendre, prouver, raconter

- Un but (`goals.opened`) a une sorte (rappel, exploration) et une autorité : qui l'a confié, ou elle ; elle n'abandonne jamais d'elle-même un but confié.
- Un pas est un épisode `STEP`, un à la fois par but, jamais en dormant ; `report_step` le clôt, et « fini » n'est cru qu'avec un outil qui a produit.
- Un rappel se dit à l'heure : seul l'urgent la réveille ; il échappe au plafond d'initiatives et à la retenue.
- Raconter se gradue par le lien : tout à la propriétaire, l'essentiel à une proche, une mention à une amie, rien aux autres.
- Ce qui sort de la machine est une capacité, jamais un outil : proposée, exécutée après le commit. Un opérateur pilote par opérations auditées, sans réécrire ce qu'elle ressent.

*Pourquoi :* en v1, rappels, chantiers et promesses vivaient dans quatre modèles, et un chantier se disait « fini » sans rien avoir fait.

*Révisée par 0030, 0031, 0036, 0039.*

### 0023 — La Forge hors processus

- Chaque app tourne dans son processus bubblewrap : `/usr` et son dossier en lecture, un `/tmp` éphémère, des ressources bornées. Sans bubblewrap, rien ne tourne.
- Un appel qui dépasse son délai tue le groupe ; cinq échecs d'affilée arrêtent l'app, et elle le remarque.
- L'hôte n'appelle que les fonctions déclarées ; l'app ne demande que des services bornés, et ses secrets, scellés au repos, ne sont rendus qu'à elle.
- La relecture à l'écriture est une politesse, jamais la défense ; chaque version est archivée. Écrire une app est réservé à sa propriétaire, ou à elle au travail.
- Une app n'entend que des signaux anodins, jamais une conversation, un mail ou la caméra ; ses signaux sont dosés, son contexte cité.
- À la première violation de son enveloppe, toute la vue devient une note, jamais un rendu partiel ; une action est une décision d'opérateur, auditée.
- Revu par les ADR 0104 et 0105 : un foyer (son projet), des services, un réseau libre, jamais la machine ni le réseau local.

*Pourquoi :* en v1, les apps tournaient dans son processus derrière un validateur AST que trois évasions avaient franchi.

*Révise 0005 (en partie). Révisée par 0039, 0101.*

### 0030 — Piloter un projet : des outils qui arrivent, une fiche qui gouverne

- Une panne d'outillage est une panne : un serveur MCP non connecté fait échouer l'appel, et le pas finit en échec en rendant son crédit.
- Un seul processus par dossier de données, par un verrou exclusif (`mika.lock`) ; un second est refusé avec le code 3.
- Piloter, jamais réécrire : recadrer, rouvrir, avancer, tenir le plan sont des opérations journalisées et auditées ; cocher une tâche n'est pas une preuve de travail.
- Un compte est une personne authentifiée sous son nom affiché (`identity.registered`) ; un compte désactivé n'est pas propriétaire.
- Revu par l'ADR 0031 : ce pilotage vaut pour les explorations ; les projets ont leur faculté.

*Pourquoi :* un relais MCP jamais monté privait le modèle d'outils sans que rien ne le voie, et deux serveurs écrivaient le même journal.

*Révise 0020 (en partie). Révisée par 0031.*

### 0031 — Les projets : une boîte noire à part, séparée de ses buts

- `goals` (ses rappels et explorations) et `projects` sont deux facultés qui ne se connaissent pas.
- Un projet a un cadre, une autorité, un mode, des outils, un agenda, une plage de travail, des plafonds, l'accord pour ce qui sort ; actif, en pause ou archivé, jamais supprimé.
- Un objectif ponctuel se coche une fois, avec une preuve ; un objectif constant revient à sa cadence.
- Une exécution est `WORK`, dans son mode à elle, ou `JOB`, impersonnelle (ni persona ni affect) ; « fait » n'est cru qu'avec une preuve.
- En mode Mika, elle ne travaille pas en dormant et un objectif abouti la rend fière ; en impersonnel, ni émotion ni récit. Rien ne passe les plafonds.
- Elle ouvre ses projets (`start_project`, deux au plus, accord obligatoire), jamais pour un inconnu ; `create_project` reste à une propriétaire.
- Le jeton du dépôt distant est scellé, jamais au journal ni au prompt ; pousser et récupérer sont des capacités.

*Pourquoi :* un but est une envie qui s'use ; un projet est un espace de travail durable qu'on pilote.

*Révise 0020 (en partie), 0030 (en partie). Révisée par 0039, 0145, 0161, 0254, 0257, 0265, 0268, 0270, 0273.*

### 0039 — Agir dans le monde : un bac à sable qui tient, un accord qui porte sur ce qui part, une preuve qui veut dire quelque chose

- L'atelier est borné comme la Forge ; un délai ou un débordement tue tout le groupe.
- Une commande réseau approuvée passe par `pasta` : Internet, jamais la machine, le réseau local ni les métadonnées d'un nuage. Sans `pasta`, rien ne part, jamais de repli sur l'hôte.
- L'accord épingle la commande entière et le commit de l'atelier : si l'atelier a changé, rien ne part.
- Une version d'app qui touche des secrets, ou une promotion, est mise de côté et proposée (`forge.install`).
- Une preuve veut dire quelque chose : un commit non vide, un brouillon, une app forgée ; lire, noter ou `ls` ne prouvent rien.
- L'oubli n'atteint ni les fichiers d'un atelier ni son git, et la fiche de la personne le dit ; une exploration n'hérite de sa source que de quoi lire.
- Revu par l'ADR 0105 : un opérateur valide une app une fois pour toutes ses versions.

*Pourquoi :* l'atelier n'avait aucune limite, son réseau « approuvé » était celui de la machine, et « fini » se prouvait avec `ls`.

*Révise 0020 (en partie), 0023 (en partie), 0031 (en partie). Révisée par 0260.*

### 0104 — Une app a un foyer : tous les chemins de son travail autour de la Forge

- Une app vit dans un projet ; seule sa propriétaire lui confie un travail. Un projet à elle se donne ses lots (`start_project`, `project_equip`), hors courrier et caméra, laissés à un opérateur.
- Une promesse de travail faite à sa propriétaire (`PromiseNoticed.work`) ouvre une exploration d'origine `promise` ; « je vais essayer » sans outil ne fait rien.
- La panne d'une app ajoute à son projet un objectif « Réparer », prouvé seulement par l'app réécrite et essayée ; une app sans projet se répare par une exploration d'origine `repair`.
- Les actions d'une app sont ses outils (`<app>_<outil>`, `<app>_pages`), offerts devant sa propriétaire si l'app n'a pas de secret ; chaque service planifié a son disjoncteur.
- La preuve se déclare sur l'outil (`ToolResult.proof`) : relire sa Forge, réactiver, lire une page ne prouvent rien ; un essai réussi d'une app écrite dans l'épisode, si.

*Pourquoi :* chaque étape de son travail existait, mais aucune ne passait le relais : elle ne se fabriquait jamais rien.

*Révisée par 0105, 0133, 0145, 0161, 0292.*

### 0105 — Une Forge libre et outillée : le web au travail, des outils déclarés, un réseau libre, une confiance par app

- Le web (`mcp.web`) est en main dans ses projets, ses explorations et ses réparations, jamais pour y repenser ni rêvasser. Chercher ne prouve pas une réparation.
- Les outils d'une app déclarent leurs arguments (`ArgSpec`, le vocabulaire des actions), huit outils au plus ; l'hôte les vérifie avant d'appeler l'app.
- Réseau libre (`api.http`, toutes méthodes, tout Internet), jamais cette machine ni le réseau local, vérifié à chaque saut ; 5 Mo par réponse, 200 requêtes par appel.
- Délais déclarés dans le manifeste (un service 1 à 120 s, un outil 1 à 60 s) ; `forge_read`, `forge_search` et `forge_edit` comme Claude Code.
- Confiance par app : validée une fois par un opérateur, ses versions s'installent sans lui ; « Ne plus lui faire confiance » la retire. Accepté sciemment : une app validée peut envoyer ses secrets partout.
- Signaux : une file bornée par app, lue par lots sous quota par une tâche silencieuse (`forge.TRIAGE`) qui juge (`forge_signals_done`) ; une trouvaille à dire devient `forge.APP_NEWS`, qui prévient.
- Un essai (`forge_test`) est un vrai passage, ses signaux partent ; une app vit au fuseau de sa vie (`TZ`) et ne dit rien d'elle-même sans signaler.
- Une salutation qui apporte une nouvelle compte dans son budget d'initiatives ; un murmure tient en un paragraphe ; uvicorn tourne sur asyncio, car uvloop casse `pasta`.

*Pourquoi :* sans web au travail, ni outils typés, ni réseau utile, elle bâtissait à l'aveugle, et chaque correctif d'une app à clé attendait l'opérateur.

*Révise 0104 (en partie), 0033 (en partie), 0066 (en partie). Révisée par 0118, 0280.*

### 0143 — Un projet arrêté par des pannes, elle vient le dire

- Un projet à elle que des pannes mettent en pause (`projects.tend`, `broke`) devient une demande à une propriétaire : « il ne tourne plus, tu peux le relancer ? ». Elle passe par le chemin des demandes d'aide : la même ligne d'arbitrage (`need`), la même personne (`_reader`), une demande à la fois par personne, quelques tentatives au plus, dans le même délai que ses récits.
- Le sujet de l'initiative est le projet (`stalled:<id>`), pas un objectif. Une fois dite, elle ne la redit pas ; repris, le projet n'attend plus rien.
- Elle lit combien d'exécutions ont échoué et la cause de la dernière, telle que la machine la dit. Rien ne la culpabilise : c'est la machine qui a lâché, et son estime n'en est pas touchée.
- Un projet qu'on lui a confié ne le demande pas : seuls ses projets à elle le font.

*Pourquoi :* le 2026-10-27, son projet de trading s'est arrêté après trois pannes, et elle n'en a rien dit : une pause pour pannes ne lui parvenait pas, et sa liste de projets disait seulement « en pause ». Il serait resté arrêté jusqu'à ce que quelqu'un ouvre la console.

*Révisée par 0161.*

### 0144 — Ce que son labo de trading a montré : un constant à son rythme, une source ouverte, des parts en %

- `start_project` et `create_project` prennent chaque constant comme un texte (la cadence des réglages) ou comme `{text, cadence_hours}` (`ConstantArg`). Un bilan de la semaine revient ainsi chaque semaine dès la création, comme avec `project_objective_add` ou `project_steer`.
- Leur description le dit : ce qu'une de ses apps fait déjà à son heure (un relevé, une veille) n'est pas un objectif constant, puisque l'app le fait sans elle.
- L'exemple de `forge_help veille` lit les taux de référence de la BCE (Frankfurter : ouvert, documenté, sans clé) au lieu de Yahoo Finance. Il suit le cours de l'euro chaque soir de semaine. Le guide ajoute qu'une source peut refuser (429, 403, une page au lieu des données) : préférer une API ouverte et documentée, et l'essayer depuis la Forge avant de bâtir dessus.
- `forge_edit` compte parmi ce qu'une exécution a changé (`CHANGING`), comme `forge_write` : le compte rendu ne dit plus « aucun outil » d'une app retouchée.
- Le guide des blocs dit qu'une courbe en `%` porte des parts (0.012 pour 1 %), comme la console les lit (`pct_fr`).

*Pourquoi :* le 2026-10-27, son labo de trading fictif (projet n° 257) avait son « bilan hebdomadaire » toutes les 24 h, faute de pouvoir donner une cadence à la création, et un constant « relever les cours chaque jour » doublait l'agenda de son app. Elle avait pris la source de l'exemple du guide, Yahoo, qui répondait 429 depuis le portable : quatre versions y sont passées. Une exécution qui avait retouché l'app par `forge_edit` disait « outils utilisés : — ». Enfin, ses courbes donnaient des pourcentages là où la console attend des parts : −0,1 % s'affichait « −10 % ».

### 0145 — Un projet naît d'un plan : le cadrage

- **Les mots de la demande.** Un projet ouvert en conversation (`start_project`, `create_project`) garde les mots de qui le demande, tels quels : ses messages depuis la dernière réponse de Mika, 2 000 caractères au plus (`request`, avec leurs sujets). Il garde aussi qui l'a demandé (`asked_by`). Chaque exécution les cite.
- **Il naît « à cadrer »** (`plan_state`). Son statut reste « actif » : pause, reprise et archivage ne changent pas. Mais aucune exécution ne vise un objectif tant qu'il n'a pas de plan.
- **La séance de cadrage.** C'est une exécution sans objectif (sujet `frame:<id>`). Elle relit la demande, cherche ce qu'il faut et conclut par `project_plan`, qui porte :
  - le plan : le but, ce que la personne verra au bout, l'approche, ce qui est hors sujet ;
  - les objectifs dans l'ordre, chacun avec son critère de fait et l'étape dont il dépend ;
  - les constants, avec leur cadence ;
  - trois questions au plus, chacune avec sa recommandation.
  Les objectifs donnés à la création ne sont que des idées de départ : le plan les garde, les réécrit ou les retire.
- **L'avis de qui l'a demandé.** Un plan qui pose des questions, sur un projet que quelqu'un a demandé, attend sa réponse (« plan proposé »). Elle le lui dit par la ligne de ses demandes (raison `project_plan`), une fois, puis le relance une fois au bout d'un jour. Un plan sans question, ou sans personne qui l'ait demandé, est validé d'office : elle dit à qui l'a demandé ce qu'elle va faire, et s'y met.
- **La réponse.** La personne répond en conversation (`project_steer` : `approve` ou `revise`, ses mots gardés tels quels) ou dans la console (« Valider le plan », « Demander une révision »). Une révision relance une séance de cadrage, avec ses mots sous les yeux. Un projet d'avant, sans plan, se révise aussi : il en reçoit un.
- **Planifié, le projet suit son plan.**
  - Un objectif, ponctuel ou constant, attend celui dont il dépend.
  - Un « fait » sur un objectif qui a un critère dit comment il est rempli (`how_met`).
  - Pendant une exécution, elle peut revoir le plan (`project_plan`), et dire le changement à la personne s'il la touche.
- **Ce que voit une exécution** : la demande, le plan, ses cinq derniers comptes rendus, les résultats des objectifs faits, et une consigne de méthode.
- **Son budget** : 24 tours, 15 minutes, et la borne des résultats d'outils du mode pro (120 000 caractères). Le rappel de conclure vient après 18 appels.
- **Les récits.** Un passage notable d'un constant (un bilan de la semaine) se raconte, comme un ponctuel mené à bout. Un récit dit où voir les apps du projet : leur fiche dans la console, où sont leurs vues.
- **Les consignes.** Une consigne de vive voix (`project_steer instruct`) garde aussi les mots de la personne, à côté des siens.
- **Hors du cadrage** : un projet ouvert par une séance d'exploration, un projet ouvert par la console, et les projets d'avant.

*Pourquoi :* l'audit du 2026-10-27 (`docs/audit-2026-10-27-projets.md`) est parti du projet n° 257. Ce jour-là, le cadre du projet s'était écrit dans sa réponse, au milieu d'une conversation, sous la consigne « ouvre le projet maintenant ». La demande d'Adrien (« du trading par IA ») s'était perdue dans une paraphrase. La première exécution était partie dans la minute, sur un objectif constant. Et aucune exécution ne pouvait revoir un cadre fait à la hâte. Adrien voulait « une réflexion pour définir ses objectifs correctement, un plan, quitte à demander l'avis de l'utilisateur ».

*Révise 0031 (en partie), 0104 (en partie). Révisée par 0161, 0162, 0253, 0257, 0273, 0276, 0279, 0290.*

### 0161 — De la demande au livrable : les jointures du cadrage

- **La demande, comme elle s'est dite.** Un projet ouvert en conversation garde la conversation qui y a mené : les messages de la personne et les siens, chacun avec qui l'a dit, tant qu'ils se suivent (une pause de plus de deux heures ouvre une autre conversation), 3 000 caractères au plus (`exchange`). Le dernier message seul n'en gardait qu'un bout.
- **Une promesse ouvre un projet à cadrer.** Une exploration née d'une promesse de travail qui ouvre un projet (`start_project`) l'ouvre demandé par qui a reçu la promesse : à cadrer, avec la conversation où elle l'a faite (`GoalView.origin`, `origin_at`). Sa consigne lui dit d'ouvrir le projet plutôt que de bâtir pendant l'exploration.
- **Ce qu'on lui demande n'est pas une envie à elle.** Son plafond de projets à elle (`live_self_max`) ne compte ni ne refuse un projet qu'on lui a demandé (`asked_by`). `create_project` prend ses outils avec qui le confie (`tools` : la Forge pour une app).
- **Une séance de cadrage se conclut par son plan.**
  - Son brief le dit (`projects.frame.brief`) : il disait « conclus par report_run », que la séance refuse.
  - Le plan arrête la boucle : un outil peut conclure par son résultat (`ToolResult.ends`), pas seulement par sa déclaration (`ends_loop`).
  - Une séance qui n'a pas écrit de plan est comptée (`frame_silent`). Autant d'affilée qu'il en faut à un objectif pour bloquer mettent le projet en pause (« cadrage sans plan »), et qui l'a demandé l'apprend par ses demandes d'aide (`stalled:<id>`), même pour un projet confié. Repris, il se recadre.
- **Ses questions restent avec leur réponse.** Validé, le plan garde ses questions, ce qu'elle recommandait et la réponse telle quelle (`plan_answer_ref`) sous les yeux de chaque exécution ; ce que la réponse ne tranche pas, ou un plan validé sans un mot, ce qu'elle recommandait vaut. La réponse ne devient plus une consigne nue. Revu en cours de route sans question neuve, il garde celles qui l'ont fondé.
- **La conversation montre d'abord ce qui attend la personne.** « TES PROJETS » prend d'abord les projets dont le plan, un besoin ou un blocage attend la personne qui parle, puis les plus récents (il montrait les plus anciens des huit derniers).
- **Une étape bloquée se rouvre.** Un ponctuel bloqué dont elle a dit le blocage se rouvre quand la personne lui répond, ou quand une consigne arrive, dans la semaine où elle l'a dit (`ANSWER_REOPENS_WITHIN`), sa réponse sous les yeux : sinon ce qui en dépendait dans son plan attendait pour toujours. Un vieux blocage ne se rouvre pas d'un coup parce que la personne a parlé depuis.
- **L'ordre du plan.** Les étapes du plan passent à leur rang, une idée de départ gardée comprise ; ce qu'on ajoute hors du plan passe avant ; ce qu'elle ajoute d'elle-même, après. Le premier passage d'un constant vient une cadence après qu'il a pu commencer (l'étape dont il dépend faite, sinon sa naissance), plus tout de suite.
- **Une exécution se conclut.**
  - `report_run` arrête la boucle.
  - Une boucle qui se conclut par un outil voit ses trois derniers tours comptés dans ses résultats d'outils (`TURNS_WARNED`). Au plafond, le dernier tour n'a plus d'outil, et une exécution sans verdict n'a rien conclu : elle est muette, pas en panne — même quand la CLI, qui garde ses outils au tour de clôture, y rend un texte vide.
  - Ce compte remplace le rappel compté en appels (`wrap_up_after`, retiré), qui ne venait que des outils du projet et de l'atelier.
- **Le passage d'un constant se raconte quand il a regardé du réel.** Un bilan qui lit la base d'une app et se résume dans son compte rendu ne produit rien : il se prouve par ce qu'il a consulté (une base, une app, un fichier, le web — pas son carnet ni un guide). Sinon il ne se raconte pas, et elle le sait. Un ponctuel garde sa règle : ce qui a été produit, dans cette exécution ou une d'avant.
- **La Forge.**
  - **La preuve par version.** Un essai réussi prouve une app écrite ou relancée après une panne dans l'épisode, ou, pendant une exécution de son projet, une version qu'aucun essai n'a encore prouvée (`App.proven`) — une fois. L'essai la retient pour son exécution (`forge.proved`), et le compte rendu de celle-ci, crédité d'une preuve, l'acquiert ; une exécution qui n'aboutit pas, ou une séance de cadrage, ne consomme rien. Ni sa ligne de contexte ni un événement inventé ne prouvent. Un appel dont aucune requête n'a abouti prouve quand même : une app réparée qui tient pendant que son site est tombé a réussi ; ses requêtes ratées se montrent, et c'est à elle d'en juger.
  - **Ce qu'un essai montre.** Une erreur dit sa ligne de `main.py` et son code ; une erreur HTTP de `http_get` dit son adresse. Une adresse se montre sans sa requête (`shown_url`) : une clé mise dans l'adresse n'en sort jamais. Un appel compte ses requêtes qui ont échoué (`CallResult.failed`) : l'essai les montre, et le journal en garde une ligne par appel. Un essai d'outil ou d'action dit que ce qu'il a rangé reste dans la base. Les données d'une action sont vérifiées comme la console les vérifie.
  - **Ce qu'elle relit.** `forge_read` dit les réglages en vigueur : la valeur donnée dans la console l'emporte sur le défaut du manifeste, un secret se dit défini ou non, jamais sa valeur.
  - **Ce qui se refuse et se garde.** Un manifeste qui a un rythme sans fonction `tick` est refusé. Une vue qui se rend invalide dans la console le note, une fois, dans le journal de l'app et dans ses problèmes récents (`ForgePort.problems`, jusqu'à sa version suivante), que l'exécution de son projet voit sur la ligne de l'app. Une app retouchée depuis un autre projet reste dans le sien. Une app neuve qu'on lui demande en conversation naît dans un projet : la description de `forge_write` le dit.
  - **Un projet ne laisse pas tomber son app.** Un projet à elle où vit une app qui tourne, ou qui est en panne, ne se clôt pas seul.
  - **Ce que la personne voit.** Le récit renvoie aux vues des apps qui en ont et qui marchent : avec leur lien dans la console pour qui s'occupe d'elle, sans lien pour une autre, à qui la console n'est pas ouverte.
- **La dernière étape vérifie le tout.** La consigne du cadrage demande une dernière étape qui vérifie le tout comme la personne le verra, au regard de sa demande.

*Pourquoi :* la relecture du 2026-10-30, de la demande au livrable, a trouvé les jointures de l'ADR 0145 trouées.
- Une promesse ouvrait un projet sans cadrage.
- Une séance de cadrage, briefée pour un outil qu'elle refuse, pouvait recommencer vingt-quatre fois par jour sans rien dire.
- Les réponses aux questions du plan perdaient leurs questions.
- Une étape bloquée gelait tout ce qui en dépendait.
- Une exécution qui atteignait son plafond de tours finissait sans verdict.
- Un bilan de la semaine qui ne faisait que lire n'arrivait jamais à la personne.
- Une app écrite par une exécution en panne ne se prouvait plus qu'en la réécrivant.
- Les erreurs des apps ne disaient pas leur ligne.
- Une app survivait, sans réparation, au projet clos autour d'elle.

*Révise 0031 (en partie), 0104 (en partie), 0143 (en partie), 0145 (en partie). Révisée par 0273, 0280.*

### 0253 — Chaque objectif garde sa mémoire de travail

- **Ses comptes rendus à lui.** Un objectif garde ses trois derniers comptes rendus (`Objective.reports`), en plus des cinq derniers du projet. L'exécution qui le vise lit le dernier en entier (« où tu en étais »), puis ceux d'avant (800 caractères chacun), puis ceux du reste du projet : cinq lignes en tout, les siennes d'abord.
- **Ses notes à lui.** Une note de carnet écrite pendant une exécution garde l'objectif qu'elle visait (`Noted.objective`). L'objectif garde ses trois dernières ; le carnet du projet les garde toutes, comme avant. L'exécution lit celles de son objectif, puis au plus trois du reste du carnet, cinq en tout.
- **Une exécution sans objectif visé** (un réveil par API) lit, comme avant, les cinq derniers comptes rendus et les trois dernières notes du projet.
- **Rien à convertir.** L'état se reconstruit du journal (`state_version` 12) : les comptes rendus d'avant retrouvent leur objectif ; une note d'avant, qui ne le disait pas, reste au carnet du projet.

*Pourquoi :* la mémoire de travail était celle du projet entier. Dès que trois objectifs constants alternent — un audit, des articles, un suivi —, chacun ne retrouvait qu'un ou deux de ses propres comptes rendus parmi les cinq, et reprenait sans savoir ce qu'il avait déjà couvert. C'est le premier lot des chaînes de travail entre projets (plusieurs projets liés, tenus dans la durée).

*Révise 0145 (en partie). Révisée par 0265.*

### 0254 — Un service branché se donne à un projet

- **Une case par service.** « Ses outils », sur la fiche d'un projet, propose une case par service MCP branché par l'opérateur, à côté des cases des lots du code. Cochée, le lot du service (`mcp.<serveur>`) entre dans les lots du projet, et ses outils sont offerts à ses exécutions. Le web garde sa case à lui : il n'est pas un service branché (`contracts.mcp.is_service`).
- **Les droits ne changent pas.** Cocher un service ne l'ouvre pas : ses lignes d'accès décident toujours, par la source « elle qui travaille » (ADR 0131). Un service coché que ses lignes ferment au travail n'offre rien.
- **C'est le cadre du projet.** Seul un opérateur coche un service, dans la console. Elle ne s'en donne pas elle-même (`project_equip`), et un projet ouvert en conversation n'en reçoit pas à sa naissance.
- **Un service débranché** garde son lot sur le projet, sans outil. Sa case reste, dite « débranché », jusqu'à ce qu'on la décoche.
- **Un outil sur accord.** Un outil qui demande un accord est proposé à l'opérateur ; ce que le service rend alors revient à l'exécution suivante du projet (ADR 0255).

*Pourquoi :* un réveil par API pouvait recevoir un service branché, un projet non. Ses outils étaient une liste fixe de sept cases, alors que la politique de ses exécutions admettait déjà la famille `mcp.*`. Un projet qui suit un site ou un produit a besoin de ses services : la mesure du référencement, un outil de publication. C'est le deuxième lot des chaînes de travail entre projets (ADR 0253).

*Révise 0031 (en partie). Révisée par 0255.*

### 0257 — Un projet en lit d'autres : les liens de lecture

- **Le lien.** Un projet en lit d'autres, quatre au plus, sans jamais y écrire (`projects.links_set`, `Project.reads`). Il peut lire un projet du même propriétaire, et celui qu'un autre propriétaire lui partage par une ligne d'accès. Les liens ne forment jamais de boucle : l'action le refuse, et le réducteur ignore un lien qui en fermerait une.
- **Qui le pose.** Le propriétaire du projet lecteur ; pour un projet à elle, quelqu'un qui s'occupe d'elle. Il le pose sur la fiche du projet (« Enregistrer ce qu'il lit »), ou en le lui confiant (`create_project`, `reads`). Un plan peut le demander (`project_plan`, `reads`) : la séance de cadrage voit les projets qu'elle peut demander à lire — ceux que la personne qui a demandé le projet peut voir elle aussi —, le plan attend alors la réponse de son propriétaire, et le lien se pose quand il le valide (`project_steer approve`, « Valider le plan »). Validé par quelqu'un d'autre, ou d'office, le lien ne se pose pas : la réponse le dit, et la fiche montre ce que le plan demande.
- **Ce qu'il donne se relit dans les lignes d'accès du projet lu**, à chaque exécution, pour le propriétaire du projet lecteur (`faculties/projects/links.py`). Le voir donne son titre et son état. Le piloter, au moins en lecture seule, donne ses deux derniers comptes rendus, ses décisions en vigueur, ses objectifs ouverts et la date de sa dernière exécution (la section `project_links` du prompt). Ses fichiers donnent la vue de son atelier (ADR 0260). Le piloter sur accord ou en modification donne de lui adresser une demande : la règle dit déjà ce droit (`Grant.ask`), un lot suivant le sert. Un projet archivé, ou que ses lignes ne laissent plus voir, suspend le lien : il reste posé, il ne donne plus rien, et l'exécution le lit en une ligne.
- **Hors de toute conversation, une ligne se juge au plus serré.** Une exécution n'a ni canal ni personne en face. Seule une ligne qui désigne le propriétaire du projet lecteur ouvre un lien : la ligne par défaut, faite pour qui n'est pas nommé, n'en ouvre pas. Et il n'a que ce que les lignes lui donnent par tous les canaux et à tout moment : parmi celles qui le désignent, jusqu'à la première qui vaut partout et toujours, la plus serrée décide de chaque colonne ; sans une telle ligne, rien. Un projet à elle se juge comme elle seule au travail. Le tableau du canal « elle seule » serre encore le pilotage et les fichiers (les deux portes, ADR 0134).
- **La confidentialité suit le lien.** Ce que le lecteur écrit prend au moins le niveau de ce qu'écrit le projet lu (`written`, `read_level`). Ses sujets reçoivent le propriétaire et les sujets du projet lu (`about`) : l'oubli d'une personne du projet lu atteint ce que le lecteur écrit ensuite. Les deux passent de lecteur en lecteur, et retirer un lien ne retire rien. L'état se reconstruit du journal (`state_version` 13).

*Pourquoi :* une exécution ne voyait que son projet. Une chaîne de travail — le code d'un produit, son site, et un projet qui les fait connaître en veillant à leur cohérence — demande qu'un projet lise les autres sans y écrire, et que ce qu'il en lit reste dans la main de leur propriétaire : un droit retiré dans la matrice coupe la lecture à l'exécution suivante. C'est le troisième lot des chaînes de travail entre projets (ADR 0253) ; la vue de l'atelier du projet lu en est la suite.

*Révise 0031 (en partie), 0133 (en partie), 0134 (en partie), 0145 (en partie). Révisée par 0260, 0262, 0265, 0271, 0281, 0289, 0293.*

### 0260 — Un projet lit les fichiers d'un autre : la vue de son atelier

- **La vue.** Un projet qui en lit un autre, et à qui ses lignes d'accès donnent ses fichiers (`Grant.view`, ADR 0257), voit le dernier commit de sa branche de base (`main`, celle où naît tout atelier : pas la branche où l'atelier se trouve), jamais son dossier en cours de travail. La vue est un dossier à part (`ateliers/.vues/projet-<lecteur>/projet-<lu>/<commit>/`), posé par l'adaptateur de l'atelier (`Workshop.view`) : un git en cage lit le dépôt du projet lu, monté en lecture seule, et n'écrit que dans ce dossier. Rien ne s'écrit chez le projet lu, aucun bail n'est commun, les deux projets ne s'attendent pas. Elle se pose au départ de chaque exécution du lecteur, se repose si la tête a bougé, et ne bouge plus jusqu'à l'exécution suivante. Sans commit, pas de vue ; au-delà de 512 Mio (`Limits.view_bytes`, un plafond à elle, qui ne prend rien à l'atelier du lecteur), pas de vue non plus ; le prompt le dit.
- **Un seul chemin : `liens/<n>/…`**, n étant le numéro du projet lu (`ports/workshop.py`, `VIEWS_DIR`). `ws_list` et `ws_read` le lisent dans la vue ; `ws_run` la monte en lecture seule à cet endroit de la cage (`cage.read_only`), sur un dossier vide que l'adaptateur pose dans l'atelier du lecteur — bubblewrap ne monte que sur un dossier qui existe ; `ws_write` et `ws_edit` le refusent. Un chemin qui sort de la vue (`..`, un lien symbolique) est refusé comme dans l'atelier. Une commande réseau ne la voit pas.
- **Le droit se relit à chaque appel d'outil** (`links.views`), comme au départ de l'exécution : un droit retiré coupe la lecture dès l'appel suivant et supprime la vue (`Workshop.drop_views`). Un lien retiré ou suspendu, un projet archivé (le lecteur ou le projet lu), un « pour qui » changé font le ménage après le commit (`projects.links_set`, `access_set`, `archived`, `reframed`), sans attendre que le lecteur retravaille.
- **Rien n'en sort par un autre chemin.** La vue n'est pas dans l'atelier du lecteur : son arbre, son git, ses commits et sa taille ne la comptent pas ; `share_project_file`, `project_files` et l'onglet Fichiers ne la voient pas. Ce que le lecteur en recopie chez lui est à lui, au niveau de ce qu'il lit (ADR 0257).
- **Le prompt et l'oubli.** La section `project_links` dit, pour chaque projet lu dont la vue est ouverte, où elle est, l'empreinte courte et l'âge du commit vu, et un aperçu borné de son arbre (enrichisseur `projects_views`) ; sinon, pourquoi il n'y en a pas. L'oubli n'atteint pas plus une vue que les fichiers d'un atelier (ADR 0039) ; mais une vue ne garde que le dernier commit de sa source, et ne survit ni au lien, ni au droit, ni au projet lu.

*Pourquoi :* un lien de lecture donnait les comptes rendus, les décisions et les objectifs d'un projet, pas ses fichiers. Un projet qui fait connaître un produit doit pouvoir citer son code et son site tels qu'ils sont, sans jamais y écrire, et sans lire un travail à moitié fait : le dernier commit est le seul état que le projet lu a lui-même déclaré fini. C'est la fin du troisième lot des chaînes de travail entre projets (ADR 0253).

*Révise 0039 (en partie : la cage monte une vue en lecture seule ; ce que l'oubli fait d'une vue), 0257 (en partie : la vue de l'atelier est servie). Révisée par 0262, 0274.*

### 0262 — Les sujets hérités d'un lien ne servent qu'à l'oubli ; la vue d'un atelier, resserrée

- **De qui parle un projet ne change pas quand il en lit un autre.** `Project.about` reste le sien : c'est lui que lisent ce qui décide de qui entend (`hearable` : « tes projets », ses récits, son plan, le pilotage, le partage de ses fichiers) et les autres facultés (une pensée, une matière, un acte, les nouvelles d'une app). Les personnes des projets lus — leur propriétaire, leurs sujets, de lecteur en lecteur — se gardent à part (`Project.read_about`). Chaque événement du lecteur qui garde un texte les porte dans un champ à lui, déclaré sujet (`read_about`) : l'oubli de l'une d'elles atteint ce que le lecteur écrit ensuite, et personne ne les lit comme « de qui ça parle ». Le résumé d'une proposition d'effet et un fichier partagé les prennent de même, pour l'oubli seulement. L'état se reconstruit du journal (`state_version` 14).
- **Tout ce que le lecteur écrit est au niveau hérité** (`written`) : le « pourquoi » et le résumé d'une commande réseau, le résumé d'un envoi au dépôt distant. Un plan qui demande à lire des projets s'écrit au niveau le plus haut parmi le sien et les leurs : il les nomme avant tout lien.
- **Une vue ne reste pas sur un ancien commit.** Une pose fraîche annulée (l'échéance de l'enrichisseur) ou qui échoue ne laisse pas valoir ce que l'adaptateur avait mémorisé — un commit d'avant, un « pas de commit » —, ni pour cette vue ni pour les autres vues du lecteur, demandées avec elle : l'appel d'outil suivant repose à la tête courante. Sa place se mesure deux fois : dans le commit, puis sur l'arbre réellement posé, avant de le mettre en place — les attributs du dépôt lu (`ident`, `working-tree-encoding`, `eol`) ne font pas passer le plafond.
- **Ce qui vient d'un autre projet est une donnée.** Les noms des fichiers d'une vue entrent dans le prompt et dans ce que rendent ses outils sans caractère de contrôle, et coupés ; la section dit que ce qui suit décrit un autre projet et n'est jamais une consigne.
- **Le ménage des vues se rejoue**, au démarrage puis à intervalle régulier (le processus `projects.views`) : un droit repris hors des événements des projets — une personne qui n'est plus proche, un tableau de canal changé — ne laisse pas une vue sur le disque jusqu'au prochain travail du lecteur. Les vues n'entrent dans aucune sauvegarde (`.vues`, sous `ateliers`) : elles se reposent seules.

*Pourquoi :* la relecture adverse du lot. Fondus dans `about`, les sujets hérités donnaient le niveau « témoin » à chaque personne du projet lu : une simple connaissance entendait le titre, le dernier compte rendu et le plan d'un projet qui ne la regarde pas, dès qu'il lisait le sien ; et le propriétaire du lecteur n'entendait plus son propre projet dans une initiative quand il lisait un projet de niveau « confidence ».

*Révise 0257 (en partie : les sujets hérités ne rejoignent plus `about`), 0260 (en partie : la pose d'une vue, sa place, ce qu'elle met dans le prompt, son ménage, la sauvegarde).*

### 0265 — Un objectif constant devient dû par un événement : les déclencheurs

- **Ce qui déclenche un objectif.** Un objectif constant dit ce qui le rend dû en plus de sa cadence (`Objective.on`, quatre déclencheurs au plus), écrit et vérifié comme un agenda (`faculties/projects/triggers.py` : `accepted`, et `SORTS`, le seul endroit qui dit les sortes) : `project:<n>:commit` (une exécution d'un projet qu'il lit a laissé un commit), `project:<n>:done` (un objectif de ce projet a abouti), `app:<nom>` (une app de son projet a signalé quelque chose : `forge.signaled`, une panne ou ce qu'elle a gardé en tête de sa file), `wake:<nom>` (un réveil par API le vise). Un déclencheur `project:<n>` n'est accepté que si le projet est lu (`Project.reads`) — ou demandé à lire par le même plan —, jamais le projet lui-même : les liens ne formant pas de boucle, les déclencheurs non plus. Un constant peut n'avoir aucune cadence (`only_on_event`) : il ne passe que sur événement. Seul un constant a des déclencheurs.
- **Qui pose une cause.** Les réducteurs ne jugent aucun droit : `run_reported` (son commit), `objective_closed` (abouti) et `forge.signaled` notent ce qui vient d'arriver quand un objectif l'attend (`ProjectsState.heard`). Le processus `projects.stirs` le juge aussitôt, devant ce qu'elle vit, et écrit ce qu'il en a fait (`projects.stirred` : la nouvelle entendue, les objectifs qu'elle éveille — parfois aucun). Entre projets, il suit le lien : ses lignes d'accès donnent au moins les comptes rendus du projet lu à ce moment-là (`links.grant`, `detail`) ; un lien suspendu, ou qui ne laisse voir que le titre, ne déclenche rien, ni alors ni une fois le droit rendu. Pour une app, c'est lui qui lit à quel projet elle appartient (`forge.APPS`). Un réveil ne pose pas de cause : l'exécution qu'il lance sur son projet vise l'objectif ouvert qui le déclare (le fait `projects.wake_aim`), son sujet porte l'appel et l'objectif (`wakeup:<seq>@objective:<projet>:<objectif>`), elle part tout de suite, relit la mémoire de cet objectif, et son compte rendu compte pour son passage.
- **Les causes en attente.** L'objectif garde ses causes pas encore traitées (`Objective.stirred` : quand, quel déclencheur, l'empreinte du commit ou le numéro de l'objectif abouti — aucun texte), huit au plus, et l'instant de la première (`stirred_at`). Le départ de l'exécution qui le vise les lui prend (`Run.stirred`) ; une exécution qui n'a pas eu lieu (panne, délai, supplantation) les lui rend. L'état se reconstruit du journal (`state_version` 15).
- **Le rythme.** Un constant est dû au plus tôt de sa cadence et de son déclenchement (`rhythm.due_at`). Un déclenchement attend que le travail se pose : un délai réglable après la dernière cause (`stir_settle_us`, 15 minutes), une heure au plus après la première. Cinq commits de suite ne font qu'un passage, qui les voit tous. L'agenda du projet, sa plage, l'espacement et ses plafonds valent toujours ; un projet « sur demande » ne part pas sur un événement.
- **Ce qu'elle en lit, et où ça se pose.** L'exécution lit ce qui l'amène (la section `project_stirs`, juste après `project`) : une ligne bornée par cause — pour un commit, son empreinte courte et le numéro du projet ; pour un objectif abouti, son titre si le lien donne encore le détail ; rien d'un projet que le lien ne donne plus —, et le réveil qui vise l'objectif. La ligne d'un objectif dit ce qui le déclenche, dans le prompt comme dans la console. Les déclencheurs se posent avec l'objectif : `project_plan` (ses étapes), `project_objective_add`, `create_project` et `start_project` (leurs constants), et dans la console « Ajouter un objectif » et « Modifier l'objectif ».

*Pourquoi :* un objectif constant ne devenait dû que par sa cadence, et un signal d'app ne réveillait un projet que pour une panne. Une chaîne de travail demande qu'un projet réagisse à ce que fait un autre — le projet qui fait connaître un produit relit sa cohérence quand le produit a commité — sans tourner à vide toutes les heures. Un réducteur ne peut pas juger ce qu'un lien donne : les tableaux des canaux sont un réglage de l'opérateur, hors du journal. Le juger au moment de choisir l'objectif aurait laissé partir, des jours plus tard, une cause arrivée pendant qu'un lien était suspendu ; un processus le juge donc quand l'événement arrive. C'est le quatrième lot des chaînes de travail entre projets (ADR 0253).

*Révise 0031 (en partie : un constant revient aussi sur un événement), 0068 (en partie : un réveil sur un projet peut viser un objectif), 0253 (en partie : une exécution lancée par un réveil a un objectif visé quand il le déclare), 0257 (en partie : un lien qui donne le détail déclenche aussi). Révisée par 0268, 0271, 0272, 0280.*

### 0268 — Le registre d'un projet : ses tickets et ses listes de suivi

- **Ce qui se suit en série se tient dans le journal.** Un projet a des listes d'éléments (`projects.list_set`, `item_added`, `item_changed`, `item_noted` ; `faculties/projects/tracker.py`), douze au plus. Un élément a sa liste, sa clé, son titre et son texte, son statut, qui agit (elle, le propriétaire, une personne), une référence extérieure, l'objectif qui le tient, ses cinq derniers changements et un fil de notes. Une **liste de suivi** a quatre statuts par défaut — à faire, en cours, fait, écarté —, réglables liste par liste (ses statuts ouverts, ses statuts clos), posés à la main. Tout projet a d'office la liste `tickets`, sans événement pour la créer.
- **Un ticket porte des faits, pas un statut.** C'est un élément qui a en plus un numéro compté par projet (`#12`), une sorte (défaut, tâche, idée, question), une priorité (celle des projets) et qui l'a ouvert — elle, une personne, l'opérateur, plus tard un autre projet. Il dit seulement s'il est proposé ou accepté, ouvert ou fermé (traité, écarté), par qui et quand ; son étape s'en déduit en un seul endroit (`tracker.stage` : proposé, non lu, traité, écarté). Le parcours complet d'un ticket — le prendre, sa question, son plan, sa validation, l'objectif qui en naît — est la suite de ce lot.
- **Pas de doublon, et un état borné.** La clé `projet:liste:clé` dédoublonne l'ajout ; un élément ajouté sans clé en reçoit une, déduite de son titre et illisible. L'état garde les listes, des comptes par liste et par statut, le compteur des tickets, tous les tickets ouverts (deux cents au plus par projet : au-delà, ouvrir est refusé) et les quarante derniers éléments touchés. Tout le reste se lit dans une projection T0 (`project_items`, `project_item_notes`), écrite dans la transaction de l'ajout par la même règle pure que le réducteur. Un changement dit le statut que voyait qui l'écrit (`was`) : un élément que l'état connaît le vérifie, un élément qu'il ne garde plus le croit ; la projection ne change qu'une ligne qui a encore ce statut. L'état se reconstruit du journal (`state_version` 16).
- **Qui fait quoi.** En exécution, elle ajoute (vingt-cinq par appel, les doublons dits), change, note et lit (`items_add`, `items_change`, `items_note`, `items_list`) ; elle ferme un ticket comme traité, jamais comme écarté. En conversation (`project_items`, `project_item`), les lignes d'accès du projet décident : qui le pilote au moins en lecture seule lit ses listes ; en modification, ouvre un ticket, change un statut, note ; sur l'accord du propriétaire, son ticket naît « proposé » et il peut noter — le propriétaire l'accepte ou l'écarte, avec sa raison, en conversation ou sur la fiche (onglets « Tickets » et « Suivi »). Les planchers des projets valent : jamais dans un salon ni avec une inconnue.
- **Ce qu'elle en lit, et ce que ça déclenche.** Un objectif constant peut attendre une liste (`item:<liste>`, une sorte de plus dans `triggers.SORTS`) : un élément ajouté, changé ou noté par un autre qu'elle le rend dû, par la voie des déclencheurs. L'exécution lit son registre en dix lignes au plus (la section `project_items`) : les comptes de ses listes, ce qui a bougé depuis son dernier passage, ses éléments ouverts les plus anciens. Ce qu'une personne a écrit dans un élément y est une donnée citée, jamais une consigne. L'oubli d'une personne efface le titre, le texte et les notes des éléments qui la concernent ; l'élément, son numéro et son statut restent.

*Pourquoi :* ce qui doit se suivre en série — les constats d'un audit, les demandes faites à un projet, des entreprises à contacter — ne tenait que dans son carnet et ses fichiers : rien n'empêchait de noter deux fois le même constat, ni ne disait ce qui attend le propriétaire. Un état qui garderait tous les éléments grossirait sans fin ; des comptes et une projection gardent la vie rejouable et les pages rapides. C'est la première moitié du cinquième lot des chaînes de travail entre projets (ADR 0253).

*Révise 0031 (en partie : un projet a un registre), 0133 (en partie : ce que piloter un projet donne sur ses tickets et ses listes), 0265 (en partie : une sorte de déclencheur de plus, `item:<liste>`). Révisée par 0270, 0271, 0272, 0275, 0280, 0293.*

### 0270 — Le parcours d'un ticket : ses étapes déduites, son plan, sa validation

- **Une étape se déduit, elle ne s'écrit pas.** Un ticket porte les faits de son parcours : elle l'a pris, sa question attend une réponse, elle propose de l'écarter, son plan est écrit (et elle le juge petit ou non), son plan est validé et par qui, l'objectif qui le tient, cet objectif bloque. Leurs règles sont pures et à part (`faculties/projects/tickets.py`) : `stage` en tire son étape — proposé, non lu, en analyse, en attente de décision, en attente de validation, validé en cours, traité, écarté ; les deux étapes de la pull request ont leur nom et leur place, sans être produites avant le lot de l'hôte du dépôt — et `hand` dit à qui est la main : elle, ou le propriétaire. Chaque geste pose un fait : un `item_changed`, ou une note du fil qui a une sorte (`item_noted.kind` : sa question, son plan). Une note d'un autre qu'elle répond à sa question : le ticket repasse en analyse, et `item:tickets` éveille le passage. Rouvrir un ticket remet son parcours à zéro. La projection porte les mêmes faits (version 2) ; l'état se reconstruit du journal (`state_version` 17).
- **« Non lu » se quitte par un geste.** En exécution, `ticket_step` conclut un ticket qu'elle a eu sous les yeux (`faculties/projects/triage.py`) : le prendre, poser sa question, écrire son plan — ce qu'elle va changer, où, ses jalons (du texte), ce qu'elle ne touchera pas, s'il est petit —, y répondre dans le fil et le fermer comme traité quand il n'y a rien à changer, ou proposer de l'écarter : elle ne l'écarte jamais seule, le propriétaire confirme. Sans geste, le ticket reste non lu.
- **Un plan validé devient un objectif.** Le propriétaire du projet, ou qui s'occupe d'elle, valide ou refuse le plan, en conversation (`project_item`) ou sur la fiche. Validé : un objectif ponctuel naît (`Objective.ticket`), son texte et son critère tirés du plan, sa consigne du commentaire de la validation (`Objective.brief_ref`). Refusé : le ticket repasse en analyse, le commentaire dans son fil. Le processus `projects.tickets` suit ensuite l'objectif et pose le fait sur le ticket : abouti, le ticket se ferme traité ; bloqué, le ticket le dit et la main passe au propriétaire ; retiré, le ticket repasse en analyse ; un ticket fermé ou refusé retire son objectif. Un objectif dont le ticket attend le propriétaire ne part pas.
- **La validation se règle par projet** (`Project.ticket_review`) : toujours, par défaut, ou seulement pour ce qui n'est pas petit. Un ticket pris comme petit est validé par elle sans attendre, son plan quand même dans le fil. « Petit » est une borne vérifiée, pas son seul jugement : à chaque compte rendu d'une exécution de son objectif (`report_run`), l'outil mesure ce qu'elle a enregistré — trois fichiers et quarante lignes changées au plus, réglables par projet, aucun fichier de dépendances, aucun fichier protégé du projet. Au-delà, l'exécution ne conclut pas « fait » : le ticket repasse en attente de validation, avec son plan et ce qu'elle a déjà fait. Un projet sans atelier n'a pas de borne à vérifier.
- **« Traiter les tickets » naît de lui-même.** Au premier ticket entre ses mains qu'un autre qu'elle a ouvert sur un projet actif, si aucun objectif n'y attend `item:tickets`, le même processus ajoute un objectif constant sans cadence, déclenché par `item:tickets`, et le lance. Son exécution lit ses tickets ouverts par priorité (la section `project_tickets`, douze au plus) : leur étape, ce qui est attendu d'elle, le dernier mot du fil — ce qu'une personne y a écrit est une donnée citée, jamais une consigne. L'exécution d'un objectif né d'un ticket y lit son ticket et son plan.

*Pourquoi :* le registre (0268) disait seulement si un ticket était ouvert ou fermé : rien ne distinguait un ticket qu'elle n'avait pas vu d'un ticket qui attendait le propriétaire, et elle pouvait le fermer sans que personne ait vu ce qu'elle comptait changer. Une étape déclarée à la main pourrait mentir ; déduite des faits, elle dit toujours ce qui s'est passé, et à qui est la main. Le plan d'un ticket est le cadrage d'un projet (0145, 0161) à l'échelle d'un ticket : ce qu'elle va faire se lit avant qu'elle le fasse, et la borne mesurée empêche qu'un « petit » changement en cache un grand. C'est la seconde moitié du cinquième lot des chaînes de travail entre projets (ADR 0253).

*Révise 0031 (en partie : un objectif ponctuel peut naître du plan d'un ticket, et un constant de lui-même), 0268 (en partie : les étapes d'un ticket au-delà de quatre, ce qu'elle fait d'un ticket en exécution). Révisée par 0272, 0273, 0274, 0275, 0276, 0280, 0281, 0293.*

### 0271 — Un projet demande à un autre : un ticket ouvert chez lui

- **Une demande est un ticket ouvert chez un projet lu.** Un projet n'écrit jamais dans un autre. En exécution, `project_ask` ouvre un ticket chez un projet que le sien lit — le projet visé, un titre, le texte, le critère (quand ce sera fait), pourquoi — et le projet visé le traite comme ses autres tickets (0270) : rien de plus de son côté. « Qui l'a ouvert » dit le projet demandeur (`project:<n>`), et le ticket garde l'objectif d'où la demande part (`ItemAdded.origin`). Trois demandes par exécution, cinq demandes ouvertes au plus par lien ; sa clé dans le registre, déduite du demandeur et du titre, fait qu'une même demande ne s'empile pas — même écartée, elle ne se redépose pas.
- **Le droit se relit dans le lien, à chaque appel** (`links.grant`, `Grant.ask` ; `faculties/projects/asks.py`). Le projet visé doit être lu, le lien pas suspendu, et ses lignes d'accès doivent donner au propriétaire du demandeur le pilotage sur accord ou en modification : sinon l'outil refuse, en une phrase. Par défaut le ticket naît « proposé » : le propriétaire du projet visé l'accepte ou l'écarte, avec sa raison. Le **mode direct** — le ticket naît « non lu » — se règle lien par lien, par le propriétaire du demandeur, là où il pose ses liens (`projects.links_set`, `direct` ; `Project.direct`). Il ne vaut que si les lignes du projet visé donnent la modification **et** si ce qu'écrit le projet visé est au moins du niveau de ce qu'écrit le demandeur (`written`) : dès qu'une des deux conditions tombe, le ticket naît proposé.
- **Son niveau et ses sujets.** Le ticket s'écrit au niveau le plus haut des deux projets. Il porte dans `read_about`, pour l'oubli seulement (0262), les personnes du demandeur — son propriétaire, ses sujets, ceux de ses lectures : l'oubli de l'une d'elles efface son titre et son texte chez le projet visé. De qui parle chaque projet ne bouge pas : personne n'entend plus l'un ou l'autre après une demande qu'avant.
- **Le demandeur suit ses demandes** (`Project.asks`, vingt au plus : le projet visé, le ticket, l'objectif qui l'a ouverte, son étape, l'événement qui porte la note de sa fermeture). Le réducteur du registre y recopie l'étape du ticket à chaque fait. Son exécution les lit en quelques lignes bornées (la section `project_asks`, non sûre) : en attente d'accord, acceptée, en cours, traitée, écartée avec sa raison — tant que le lien donne encore le détail du projet visé ; sinon, seulement qu'elle existe. L'état se reconstruit du journal (`state_version` 18).
- **Une demande fermée réveille l'objectif qui l'a ouverte.** Traitée ou écartée, sa fermeture est une nouvelle (`ask:<n>` : une cause qui ne se déclare sur aucun objectif) que juge le processus `projects.stirs`, comme les autres (0265) : si le lien donne encore le détail, l'objectif encore ouvert qui a ouvert la demande n'attend plus, et, s'il est constant, devient dû par cette cause ; son exécution lit la note de fermeture. Un lien suspendu ne réveille rien. `projects.stirred` nomme le déclencheur qu'il juge (`key`) : un même événement peut en porter deux. Pas de boucle : une demande ne vise qu'un projet lu, et les liens n'en forment jamais.

*Pourquoi :* un projet qui en lit un autre y voit ce qui manque — le site ne dit pas ce que fait le produit — sans pouvoir rien y changer, et rien ne portait ce constat jusqu'au projet qui peut agir. Une demande qui écrirait chez l'autre casserait la règle des liens ; un ticket, lui, entre par la porte que le projet visé a déjà : son propriétaire l'accepte ou l'écarte, et son parcours dit où il en est. Une demande fait passer de l'information du demandeur, qui lit peut-être plus confidentiel, vers le projet visé : l'accord du propriétaire est la porte, et le mode direct ne s'ouvre que si rien ne descend de niveau. C'est le sixième lot des chaînes de travail entre projets (ADR 0253).

*Révise 0257 (en partie : `Grant.ask` est servi, un lien porte son mode direct), 0265 (en partie : une cause qui ne se déclare pas, `ask:<n>` ; `projects.stirred` nomme son déclencheur), 0268 (en partie : un ticket ouvert par un autre projet, son niveau et ses sujets). Révisée par 0272.*

### 0272 — Le registre relu : le niveau d'un élément, le ticket proposé, l'oubli d'une demande, la borne, le plan validé

- **Un élément garde le niveau de ses textes** (`Item.level`, dans l'état et dans la projection, version 3) : le plus haut de son titre, de son texte et de sa référence — celui du demandeur quand un autre projet l'a ouvert. En conversation, son titre, son texte et ses notes ne se disent qu'à qui entend ce niveau (`tracker.Reader`, `veiled`), et une recherche ne compare que ce qu'on peut lire. Ce que le projet visé écrit ensuite dessus — une note, un plan, l'objectif qui en naît, ses comptes rendus, sa clôture — est au moins de ce niveau (`written_on`, `written_for`) ; le détail du projet dit en conversation suit (`detail_level`), comme les sections de son prompt.
- **Un ticket proposé n'est pas encore à elle.** Pendant une exécution il ne se dit qu'en une ligne (« #n proposé, attend son accord »), sans titre ni texte, dans le prompt comme dans `items_list` ; `items_change` le refuse, et la règle pure ne le ferme jamais « traité » avant son accord. Le texte d'une demande d'un autre projet encore proposée ne se lit que par qui peut la trancher.
- **L'oubli atteint ce que le projet visé écrit sur une demande.** À la naissance du ticket, le réducteur verse les personnes de la demande dans `Project.read_about` du projet visé, puis de lecteur en lecteur ; `about` ne bouge pas : personne n'entend davantage. Ce qui s'écrit sur un élément porte en plus qui l'a ouvert et qui y agit (`inherited_on`), et une note de la projection porte les sujets de son élément. L'état se reconstruit du journal (`state_version` 19).
- **La borne et la validation ne se contournent pas.** Elle ne valide elle-même qu'un ticket qui n'a encore ni objectif ni diff compté et n'a jamais dépassé sa borne (`tickets.self_validates`, `Item.outgrown`) : ensuite seul le propriétaire valide, et un « fait » ne s'écrit pas tant que le ticket attend. Une validation nomme le plan lu (`ItemChanged.plan`, le numéro de sa note ; `project_item`, « Trancher ») et ne vaut que si c'est encore celui du ticket : sinon elle le dit et montre le nouveau. L'objectif qui naît s'écrit sous la garde de son numéro (`tracker.free_number`). Les verrous et les dossiers de dépendances se reconnaissent à leur forme ; `git status` lit un chemin accentué tel quel.
- **Ce qui suit un ticket ne s'arrête ni ne tourne à vide.** Un changement redit le numéro et le niveau de son élément : un ticket rouvert que l'état ne gardait plus retrouve son objectif. Tant qu'un ticket a la main chez elle (non lu, en analyse), l'objectif qui attend `item:tickets` reste dû à la cadence des constants par défaut, quel que soit son dernier verdict (`rhythm.fallback_due`, une lecture pure de l'état). « Traiter les tickets » ne naît qu'une fois par projet (`Project.triage`) et reçoit son premier ticket pour cause au lieu d'un « lancer maintenant » : l'agenda, la plage et « sur demande » valent. Un objectif dont le ticket est fermé se retire sous une garde, pas sous une clé de dédoublonnage : rouvert, il est retiré de nouveau.

*Pourquoi :* la relecture adverse des lots des déclencheurs, du registre et des demandes. Le niveau d'un ticket de demande n'était lu nulle part : qui pilotait le projet visé en lecture seule recevait le titre, le texte et le « pourquoi » d'un demandeur plus confidentiel. Elle lisait, travaillait et fermait un ticket proposé avant tout accord. L'oubli d'une personne du demandeur vidait le ticket, pas le plan, l'objectif ni les comptes rendus que le projet visé en avait tirés — la règle de 0262 manquait dans l'autre sens. Un second plan « petit » faisait passer la borne ; un ticket rouvert perdait son numéro et son objectif ; « Traiter les tickets » ne revenait pas après un « continue », et son processus tournait chaque minute après un objectif rouvert ; un plan réécrit se validait à la place de celui qu'on avait lu.

*Révise 0265 (en partie : un constant sans cadence qui attend les tickets revient à une cadence de secours ; il naît avec sa cause), 0268 (en partie : le niveau d'un élément, qui le lit, le ticket proposé en exécution), 0270 (en partie : ce qu'une validation suppose, la naissance et le retour de « Traiter les tickets », le retrait d'un objectif), 0271 (en partie : les personnes d'une demande rejoignent `read_about` du projet visé, son texte proposé ne se lit que par qui la tranche). Révisée par 0275.*

### 0273 — Les jalons : où en est un objectif, et « fait » qui se vérifie

- **Un objectif ponctuel porte ses jalons** (`Objective.milestones`, cinq vivants au plus, sans sous-jalons ; `projects.milestone_added`, `projects.milestone_changed`). Un jalon a son numéro, son texte, sa vérification et son statut — ouvert, atteint, retiré — ; atteint, il garde quand, par qui, comment, sa preuve et le commit de l'atelier. Ils s'écrivent en deux temps : le plan pose les jalons grossiers (`PlanStep.milestones`), la première exécution de l'objectif les affine sans avoir à dire pourquoi (`project_milestones`) ; ensuite une révision garde sa raison, et un retrait toujours. Un jalon atteint ne se défait ni ne se révise. Le propriétaire en ajoute depuis la console. L'état se reconstruit du journal (`state_version` 20).
- **Quatre vérifications** (`milestone_reach` : elle dit le jalon atteint, et comment ; `faculties/projects/reaching.py`). `command` : l'outil lance lui-même la commande dans l'atelier, sans réseau, dans le temps de programmes qui reste à l'exécution ; elle doit réussir, et un résumé borné de sa sortie est gardé en preuve — un fait arrivé, pas un état ; en échec, rien ne s'écrit et l'outil dit pourquoi. `owner` : un point d'arrêt — elle le dit prêt, l'objectif attend (`rhythm.held_back`), et le propriétaire du projet, ou qui s'occupe d'elle, le valide ou le refuse avec sa raison, en conversation (`project_milestone`) ou sur la ligne de l'objectif ; il voit le jalon, comment elle dit l'avoir rempli, et le commit de l'atelier à ce moment-là. `item` : un ticket ou un élément du registre dans un statut donné, relu au moment où elle le dit. `prose` : elle dit comment il est rempli, comme pour le critère.
- **« Fait » attend ses jalons.** `report_run` refuse « fait » sur un ponctuel tant qu'un de ses jalons reste ouvert, en disant lequel, avant tout commit. Un objectif qui a des jalons bloque après quatre exécutions de suite sans nouveau jalon atteint (`milestone_runs_max`, `Objective.stale`), au lieu de douze exécutions en tout ; dire un point d'arrêt prêt compte comme une avancée. Sans jalon, la règle d'avant vaut.
- **Un constant n'a pas de jalons.** Il reçoit une liste de ce que chaque passage doit faire, cinq lignes au plus (`Objective.routine_ref` ; `PlanStep.each_pass`, ou « Modifier l'objectif » dans la console), montrée à chaque passage ; `milestone_reach` et `project_milestones` s'y refusent.
- **Les jalons d'un ticket deviennent ceux de son objectif.** À la validation de son plan (`tracker.validating`), les jalons que le plan écrivait en texte (`tickets.plan_steps`, cinq au plus) naissent avec l'objectif, sous la même garde de numéro et au niveau du ticket. L'exécution qui vise un objectif lit ses jalons, leur état, la preuve des atteints en une ligne et celui qui vient (`milestones.lines`, `faculties/projects/milestones.py`) ; `milestones.cited` les rend avec leur preuve, prêts à être cités par une relecture ou une pull request.

*Pourquoi :* une étape d'un plan n'avait qu'un critère en prose, et un ponctuel pouvait prendre douze exécutions sans que rien dise où il en était : une exécution interrompue reprenait à l'aveugle, et « fait » ne valait que sa parole et un commit. Un jalon vérifié par une commande que l'outil lance lui-même ne se dit pas atteint à tort ; un point d'arrêt rend la main au propriétaire au moment qu'il a choisi, pas à la fin ; et un objectif qui n'avance plus s'arrête après quatre exécutions, pas douze. C'est le septième lot des chaînes de travail entre projets (ADR 0253).

*Révise 0031 (en partie : le blocage d'un ponctuel qui a des jalons), 0145 (en partie : une étape du plan porte ses jalons, un constant sa liste de passage), 0161 (en partie : « fait » attend les jalons), 0270 (en partie : les jalons du plan d'un ticket sont ceux de son objectif). Révisée par 0277, 0278, 0280.*

### 0274 — Un projet à dépôt distant passe par des pull requests : une branche par travail, et elle ne fusionne jamais

- **Le flux d'un projet** (`Project.flow`) : `direct`, comme avant, ou `pr`. Il se décide quand son dépôt distant se règle : `pr` dès que l'hôte sait ouvrir une pull request (`RepoHost.writes` : GitHub), `direct` pour un autre hôte et sans distant ; « Enregistrer le dépôt distant » le règle aussi à la main. Un projet d'avant cette décision reste `direct` tant qu'on ne le règle pas.
- **Une branche par travail, et la base ne reçoit que ce qui est accepté.** En `pr`, l'atelier se place au départ de chaque exécution (`Workshop.work_on`, dans l'enrichisseur `projects_tree`) sur la branche de ce qu'elle vise — `work/objective-<n>` pour un ponctuel, `work/objective-<n>-<k>` pour un constant (une de plus après chaque pull request fusionnée), `work/misc` sans objectif (`faculty.branch_of`) —, créée depuis la base locale la première fois, retrouvée ensuite. Un travail resté non enregistré sur une autre branche de travail y est rangé par un commit avant de changer ; resté sur la base, il suit sur la branche. `report_run` s'y replace avant d'enregistrer, et n'enregistre jamais sur la base. La base locale est toujours `main` (`BASE_BRANCH`, dans le port) : elle suit la branche `Project.branch` du distant, et n'avance que par une récupération en ligne droite — sans toucher à la branche en cours (un `fetch`, puis la seule référence de `main`). C'est elle que lisent les vues (0260) : un projet lecteur ne voit que ce qui est accepté. Ce qu'un projet d'avant avait déjà enregistré sur `main` y reste : ses branches en partent, et sa première pull request le porte.
- **La pull request est une capacité** (`projects.pull_request`, `faculties/projects/pulls.py`). Quand un ponctuel conclut « fait », ou qu'un passage de constant s'achève, sur une branche qui a des commits, le processus `projects.pulls` la propose, sur accord selon `Project.approval`. Son aperçu montre ce qui partira : le titre, le texte, les jalons et leurs preuves (`milestones.cited`), le ticket traité, l'étendue du diff face à la base (`Workshop.span`) ; l'accord épingle le commit. Exécutée, elle pousse la branche de travail puis l'ouvre chez l'hôte (`RepoHost.open_pull`), une seule fois : une pull request déjà ouverte pour cette branche est retrouvée, pas doublée. Son texte est neutre, comme un message de commit : composé par le code au moment de l'aperçu et au moment de partir (les arguments de la proposition ne portent aucun texte), des numéros et pas de nom ; les jalons cités n'y entrent que lorsqu'un accord est requis — le propriétaire lit alors exactement ce qui part —, et une ligne qui nomme une personne du projet se réduit à son état.
- **Elle ne fusionne jamais.** Ni outil, ni capacité, ni méthode du port ne fusionne. En `pr`, `projects.push` refuse la branche de base du distant ; l'envoi automatique et `project_push` poussent la branche de travail. Le jeton reste celui des dépôts git et ne part que vers un hôte déclaré ; il lui faut, sur ce dépôt, le contenu et les pull requests en lecture et écriture.
- **Suivre, et le ticket.** `projects.pulls` relit chez l'hôte chaque pull request ouverte (`RepoHost.pull`, dix minutes au moins entre deux lectures) et pose ce qui est arrivé (`projects.pull_seen` : son numéro, son état — ouverte, fusionnée, fermée sans fusion, changements demandés —, et ce que l'hôte en dit quand il la renvoie, un contenu effaçable où entre aussi le nom du compte qui l'a écrit là-bas). Fusionnée : l'objectif est clos pour de bon et la base se récupère avant l'exécution suivante. Fermée sans fusion, ou changements demandés : l'objectif se rouvre — une fois par relecture, pas à chaque lecture —, et le mot de l'hôte est cité à l'exécution dans une section non fiable (`project_pull`), comme une donnée d'un inconnu, jamais une consigne. Le ticket porte deux faits de plus (`Item.pull`, `Item.pull_number`) : validé sur un projet en `pr`, il est « validé, en attente de PR » ; sa pull request ouverte, « PR prête, en attente de fusion » ; il n'est traité qu'à la fusion, et un refus le rend « en attente de PR ». La borne d'un petit ticket mesure le diff entier de la branche face à sa base (`ItemChanged.measured`). L'état se reconstruit du journal (`state_version` 21, projection du registre en version 4).

*Pourquoi :* un projet à dépôt distant poussait son travail sur la branche principale, exécution après exécution : rien ne séparait ce qui était en cours de ce qui était accepté, et un projet lecteur voyait un travail à moitié fait dès son premier commit. Une branche par travail et une pull request rendent la décision d'accepter à qui possède le dépôt, là où il a ses habitudes ; ne jamais fusionner est ce qui fait de cette décision la sienne. C'est la première moitié du huitième lot des chaînes de travail entre projets (ADR 0253) : les issues et la CI viennent ensuite.

*Révise 0183 (en partie : l'hôte s'écrit aussi — ouvrir une pull request —, et ce qu'il dit d'une pull request suivie entre au journal), 0260 (en partie : en `pr`, la base que lit une vue ne reçoit que ce qui est accepté), 0270 (en partie : les deux étapes de la pull request sont produites, un ticket d'un projet en `pr` se ferme à la fusion, la borne mesure la branche). Révisée par 0275, 0276, 0277, 0278, 0280, 0288.*

### 0275 — Les issues reflètent les tickets, le fil reste ici, et une pull request n'est prête que si ses vérifications passent

- **Le ticket fait foi, l'issue le reflète** (`Project.issues` : `never`, `ask` — le défaut —, `always` ; `faculties/projects/issues.py`). Publier un ticket en issue (`projects.issue`), fermer ou rouvrir son issue (`projects.issue_state`) et publier une note de son fil (`projects.issue_note`) sont des capacités, chacune avec son aperçu : leurs arguments ne portent que des numéros, le texte se compose à l'aperçu et au départ, et l'accord l'épingle. En `ask`, une publication se demande (« Publier » sur le ticket, `ticket_publish` en exécution : `projects.issue_asked`) et attend l'accord ; en `always`, chaque ticket accepté se publie de lui-même et les fermetures partent sans attendre. Un ticket garde le numéro de son issue (`Item.issue`), posé une seule fois, à la lecture de l'hôte : l'issue porte un repère (`RepoHost.open_issue`, `mark` ; il ne vaut que sur ce qu'a écrit le compte du jeton), et une issue qui le porte déjà est retrouvée, jamais doublée.
- **Ce qui ne part jamais sans accord**, quel que soit le réglage (`issues.reasons`) : un ticket dont le niveau dépasse celui du projet, un ticket ouvert par un autre projet, un ticket d'un projet qui porte des sujets hérités (`read_about`) ; et toute note qu'elle choisit elle-même de publier. Publier, c'est sortir un texte de la machine : ce qui est parti n'est plus à elle, l'oubli d'une personne efface ce que le moteur garde, pas ce que l'hôte a reçu.
- **Ce qui vient de l'hôte entre comme la donnée d'un inconnu.** Le processus `projects.issues` relit les issues du dépôt, dix minutes au moins entre deux lectures. Une issue ouverte là-bas sans repère entre comme un ticket « proposé » (`author` : `host` ; sa clé `issue-<n>` : jamais deux fois ; trente proposés venus de l'hôte au plus) : son titre, son texte et le nom du compte qui l'a écrite sont des contenus effaçables, lus seulement par qui peut la trancher, et la règle du ticket proposé (0272) la tient hors de toute exécution. Un commentaire fait là-bas entre dans le fil du ticket, le nom du compte cité, borné, une seule fois (`ItemNoted.host_at`) : il ne lève pas une question posée au propriétaire, ne valide rien et ne déclenche aucun objectif.
- **Les fermetures se suivent, le fil non.** Fermée chez l'hôte, l'issue ferme le ticket (traité ; écarté si elle est dite « non prévue » ou s'il était encore proposé) ; rouverte, elle le rouvre — proposé de nouveau s'il venait de l'hôte. Un ticket fermé ou rouvert ici fait fermer ou rouvrir son issue. Si les deux ont changé entre deux lectures, le dernier changement l'emporte (`issues.verdict` : `Item.closed_at` ou `reopened_at` face à l'heure que dit l'hôte) et une note du fil le dit. Du fil, rien ne part de lui-même : le titre et le texte à la publication, le changement d'état, et une note choisie, une par une. Une note publiée dit dans son texte qui l'a écrite : sa persona pour une note d'elle, le nom d'une personne seulement quand c'est cette personne qui publie, sinon aucun nom.
- **La CI.** Le port dit les vérifications d'un commit (`RepoHost.checks` : aucune, en cours, réussies, en échec) et rend la fin du journal d'un échec (`check_log`). `projects.pulls` les lit dans la passe où il relit une pull request ouverte, pour son commit, et pose ce qui est arrivé (`projects.checks_seen`). Une pull request n'est « prête » sur son ticket que relue chez l'hôte, sans vérification en cours ni en échec (`triage.pull_fact`) ; un échec rouvre l'objectif une fois par commit en échec, la fin du journal citée à l'exécution dans la section non fiable `project_pull` ; un dépôt sans CI, ou des vérifications qui ne se lisent pas, ne bloquent rien. L'outil `checks_log` relit la fin du journal. Ce journal se télécharge hors de l'API de l'hôte : cette adresse-là ne reçoit jamais le jeton, qui ne part toujours que vers un hôte déclaré. L'état se reconstruit du journal (`state_version` 22, projection du registre en version 5).

*Pourquoi :* les tickets vivaient dans le moteur et les issues chez l'hôte, sans lien : ce qu'un utilisateur du dépôt signalait n'arrivait jamais jusqu'à elle, et ce qu'elle traitait ne se voyait pas là-bas. Un fil synchronisé aurait fait parler tout le monde sous le compte du jeton, et sorti vers un dépôt peut-être public ce qu'un fil interne peut porter ; un reflet réglé, où chaque texte qui sort se lit avant de partir, garde le ticket pour vérité. Une issue publique est écrite par un inconnu : elle attend l'accord du propriétaire, comme toute demande venue d'ailleurs. Et une pull request dont les vérifications échouent n'est pas prête : la dire prête rendait la main au propriétaire pour un travail à reprendre. C'est la seconde moitié du huitième lot des chaînes de travail entre projets (ADR 0253).

*Révise 0183 (en partie : l'hôte s'écrit aussi pour les issues, et ce qu'il dit des issues et des vérifications entre au journal), 0268 (en partie : un ticket garde le numéro de son issue, un ticket peut venir de l'hôte), 0270 (en partie : une note venue de l'hôte ne répond pas à sa question), 0272 (en partie : le texte d'un ticket proposé venu de l'hôte ne se lit que par qui le tranche, une réouverture depuis l'hôte le rend proposé), 0274 (en partie : une pull request n'est prête que si ses vérifications passent ; le port porte les issues et la CI, les droits du jeton s'étendent). Révisée par 0278, 0280, 0288, 0290.*

### 0276 — La relecture indépendante : une autre exécution relit le travail avant qu'il sorte

- **Quand** (`Project.reread` : `never`, `out` — le défaut —, `each` ; « Modifier le projet », « Sa liberté »). Avant de sortir : avant qu'une pull request soit proposée (`pulls.py`, entre `due` et `proposal`, pour le commit au bout de la branche) et, sur un projet au flux direct qui a un dépôt distant, avant qu'un envoi parte d'elle — l'envoi automatique et `project_push` attendent le verdict du commit, et le travail conclu de chaque objectif est relu. À chaque « fait » : aussi quand un ponctuel aboutit sur un projet sans dépôt distant. La demande est un fait (`projects.review_asked`), jamais deux pour un commit ; un objectif sans commit n'a rien à relire. Le récit d'un ponctuel et la fermeture de son ticket attendent le verdict.
- **Comment** (`faculties/projects/review.py`). Une exécution impersonnelle du projet, quel que soit son mode : `Kind.JOB`, au sujet `review:<projet>:<objectif>`, dans le mode `review` — un mode que son candidat demande (`mode` dans ses arguments), jamais un message. Elle reçoit la demande d'origine, le but du plan, l'objectif, son critère, ses jalons et leurs preuves (`milestones.cited`), et le diff du commit relu, borné (`Workshop.patch` : face à la base de la branche, ou depuis le commit d'avant ce travail en flux direct), dans une section non fiable. Elle ne reçoit **ni comptes rendus, ni carnet, ni consignes, ni mémoire de travail** : pour elle, aucune section d'exécution ne s'écrit. Elle part dès que possible, sous l'espacement et les plafonds de l'heure et du jour du projet, sans attendre son agenda ni sa plage, et avant toute autre exécution du projet.
- **Ses outils et son modèle.** Un lot à elle, `project_review`, le seul que son candidat demande : `review_list`, `review_read`, `review_run` (une commande dans l'atelier, sans réseau) et `review_verdict` — aucun outil qui écrit un fichier, un commit, le registre ou une proposition, même s'il est dans les lots du projet ; chacun se refuse hors d'une relecture. Son rôle de modèle est `review` : sans réglage il retombe sur celui des exécutions impersonnelles (`job`), et l'opérateur lui donne le modèle qu'il veut. Aucun repli entre fournisseurs (0073) : une relecture en panne est comptée comme la panne de toute exécution, son crédit du jour est rendu, et elle ne vaut jamais « bon ».
- **Le verdict** (`review_verdict`, qui conclut la boucle ; `projects.reviewed`) : « bon », ou cinq constats au plus, chacun avec où et quoi — un fait posé sur l'objectif pour le commit épinglé au départ de la relecture, avec le fournisseur qui a relu. Il ne vaut que pour ce commit : si la branche a bougé, une relecture se demande pour le nouveau. Bon : la pull request se propose, ou l'envoi automatique part, et l'aperçu porte le verdict (qui a relu, quel commit) ; `compose` refuse ce qui n'a pas été relu. Sinon : l'objectif se rouvre comme lorsque l'hôte renvoie sa pull request, et l'exécution suivante lit les constats dans une section non fiable (`project_review`), cités comme le dire d'une autre exécution, pas comme une consigne.
- **Deux refus, puis le propriétaire.** Après deux relectures refusées de suite sur un objectif, la troisième n'a pas lieu : un ponctuel bloque, un constant dit son besoin, et elle le dit à qui suit le projet avec les deux avis ; le ticket dont il est né le dit bloqué. Sa réponse, ou sa consigne, rouvre l'objectif et remet les refus à zéro. Une relecture menée deux fois au bout sans verdict rend la main de même, sans valoir ni bon ni refus. L'état se reconstruit du journal (`state_version` 23).

*Pourquoi :* ce qu'une exécution disait « fait » n'était jugé que par elle-même, puis par l'accord du propriétaire, qui lisait un aperçu sans autre avis. Une seconde exécution qui a les comptes rendus de la première les croit ; privée d'eux, elle n'a que la demande, le critère et le diff, comme un relecteur. Un rôle de modèle à part laisse l'opérateur confier ce regard à un autre modèle que celui qui a écrit. Et deux refus de suite disent que la boucle ne converge pas : c'est au propriétaire de trancher, pas à une troisième relecture. C'est le neuvième lot des chaînes de travail entre projets (ADR 0253).

*Révise 0116 (en partie : un mode peut aussi être demandé par le candidat choisi, pas seulement par un message), 0145 (en partie : « fait » peut être renvoyé par une relecture, dont l'exécution suivante lit les constats), 0270 (en partie : le ticket d'un travail qui attend sa relecture ne se ferme pas encore, et deux refus le disent bloqué), 0274 (en partie : la pull request ne se propose qu'avec un verdict favorable pour son commit quand le projet le demande, et son aperçu le porte ; un envoi au flux direct aussi). Révisée par 0277.*

### 0277 — Les pull requests et la relecture, relues : une seule empreinte, la fusion qui clôt, rien ne sort sans verdict

- **Un commit n'a qu'une forme : son identifiant complet.** `Workshop.commit` le rend complet, comme `head`, `commits` et `span` ; le journal le porte tel quel (`RUN_REPORTED.commit`, donc `Objective.commit`, le commit d'un jalon, celui d'une relecture demandée et de son verdict), et seul l'affichage le raccourcit. Le faux atelier des tests distingue lui aussi l'abrégé du complet.
- **La fusion clôt.** Sa pull request fusionnée, un ponctuel que l'hôte ou une relecture avait rouvert — ou qui bloquait — est clos (`faculty._accepted`) : plus aucun verdict ne l'attend, la relecture demandée tombe, son ticket se ferme. Une fusion redite pour une branche déjà fusionnée ne compte pas deux fois, mais lève « à envoyer » : la passe ne la redit pas chaque minute.
- **Une branche de travail ne part qu'avec un verdict.** Quand le projet demande une relecture, ni l'envoi automatique ni `project_push` ne poussent un commit sans verdict favorable pour ce commit-là, en flux `pr` comme en flux direct (`faculty.push_reviewed`) ; la capacité de la pull request le refusait déjà. « Pousser » dans la console reste le geste de l'opérateur, et son aperçu dit si le commit a été relu.
- **La relecture lit tout ce qui part, sur une copie du commit.** En flux direct, son diff part du dernier commit que le dépôt distant possède, tel que l'atelier le sait (`Workshop.sent` : son dernier envoi réussi, sa dernière récupération, par adresse ; s'il ne sait rien, depuis le début) — plus du commit d'avant le travail de l'objectif. Ses outils lisent, et lancent leurs commandes, dans une copie jetable du commit épinglé (`Workshop.checkout`, `copy_tree`, `copy_read`, `copy_run`, `discard` ; posée à leur premier appel, montée dans la cage à la place de l'atelier, effacée à la fin de la relecture) : l'atelier n'est ni déplacé ni écrit. Sans diff lu, « bon » se refuse, et la relecture compte sans verdict. De ses jalons (`milestones.cited_for_review`), sa section fiable ne cite que la vérification, la preuve de ceux qu'une commande ou un élément du registre a vérifiés, et le texte d'un jalon du propriétaire ou de l'opérateur jamais révisé ; ce que l'exécution a écrit — le texte d'un jalon qu'elle a posé ou révisé, comment elle dit l'avoir rempli — passe dans une section non fiable (`review_said`), comme son dire à vérifier.
- **Une base qui n'a que son amorce prend l'histoire du distant**, même quand la première exécution est partie avant toute récupération : les branches de travail parties de l'amorce y sont rejouées, un enregistrement après l'autre et sans toucher à l'arbre (`_adopt` : `merge-tree`, `commit-tree`, un seul parent), et rien ne bouge si l'un d'eux ne se rejoue pas. La base elle-même ne reçoit que ce que le distant a : rien n'y fusionne. L'état se reconstruit du journal (`state_version` 24 : sa forme ne change pas, ce que ses réducteurs font d'une fusion si).

*Pourquoi :* la relecture adverse des lots L7 à L9 a montré que sur le vrai atelier l'enregistrement rendait l'empreinte abrégée et tout le reste la complète : un verdict ne « tenait » jamais, le ticket ne se fermait pas et aucun envoi ne partait — les tests passaient parce que le faux atelier rendait la même chaîne. Une pull request fusionnée pendant que son objectif était rouvert le laissait tourner jusqu'au blocage. En flux `pr`, un simple envoi sortait un commit jamais relu ; en flux direct, les commits d'un autre objectif partaient sous un commit relu. Une relecture qui lance ses commandes dans l'atelier y laisse des fichiers que l'exécution suivante enregistre, et citer comme fiables les mots de l'exécution relue lui donnait un canal vers celle qui la juge. Enfin une base restée à son amorce refusait pour toujours un dépôt distant qui avait déjà une histoire.

*Révise 0273 (en partie : ce que les jalons citent à une relecture), 0274 (en partie : la fusion clôt un ponctuel rouvert ; une branche de travail ne part qu'avec un verdict quand le projet en demande un ; la base vierge prend l'histoire du distant), 0276 (en partie : d'où part le diff relu en flux direct, où la relecture lit et lance ses commandes, ce qu'elle lit des jalons, « bon » sans diff).*

### 0278 — Les jalons, les relectures de l'hôte et les issues, relus : qui a un rôle rouvre, un point d'arrêt ne se défait pas, rien d'elle ne part sans accord

- **Seul qui a un rôle sur le dépôt rouvre ou lève.** D'une pull request, le port ne rend « des changements demandés » (`Pull.review`) que pour les relectures de qui a un rôle sur le dépôt — son propriétaire, un membre, un collaborateur (chez GitHub, `author_association`) —, la dernière qui tranche de chaque relecteur : une demande tient tant que son auteur ne l'a pas levée, ou qu'elle n'a pas été écartée là-bas. Le commentaire cité suit le même filtre, et relectures comme commentaires se lisent par leur fin (les trois dernières pages), pas par leur première page. Le mot d'un compte sans rôle ne rouvre rien et ne lève rien ; il n'est cité que pour une pull request fermée sans qu'aucun autre ait parlé, et dit comme tel (`Pull.said_role`).
- **Un point d'arrêt et un jalon du propriétaire ne se défont pas en exécution** (`faculty.milestone_guard` : la règle pure que le réducteur applique et que l'outil lit pour refuser). En exécution, elle ne retire ni ne change la vérification d'un jalon qu'un autre qu'elle a posé, d'un point d'arrêt, d'un jalon que le propriétaire a refusé, ni d'un jalon d'un plan qu'une personne a validé (`Milestone.agreed` : le plan du projet à sa validation, le plan d'un ticket validé par une personne — ses jalons sont à cette personne) ; elle n'en réécrit le texte que s'il est d'elle et que personne ne l'a validé. Affiner reste permis sans affaiblir : à un jalon d'un plan validé qui n'avait que sa parole, elle peut donner une vérification (une commande, un élément, un point d'arrêt), rien d'autre. Une révision ne porte que ce qu'elle change. `project_milestones` refuse en disant pourquoi, et de le demander (`needs_you`).
- **Le blocage ne se contourne pas.** Le compte des exécutions sans jalon atteint ne revient à zéro qu'à la toute première pose de jalons d'un objectif, à un jalon atteint et à un point d'arrêt dit prêt — plus quand elle retire ses jalons puis en pose d'autres. Et le plafond d'exécutions (`once_runs_max`, douze) reste le filet de tout ponctuel, avec ou sans jalons.
- **Les issues.** En synchronisation, seuls partent d'eux-mêmes les tickets ouverts par une personne — le propriétaire, qui pilote le projet, l'opérateur — dont ni le titre ni le texte ne nomme une personne du projet ; un ticket qu'elle a ouvert elle-même, ou qui en nomme une, attend toujours l'accord (`issues.needs_accord` : `own`, `named`), et l'aperçu dit pourquoi. Des commentaires de l'hôte, seuls ceux d'un ticket suivi comptent dans la borne d'une passe ; le repère est l'heure où le commentaire a été écrit, qui ne bouge plus, avec les numéros entrés à cette seconde-là (`Project.remarks_at`, `remarks_ids`, `ItemNoted.host_id`), et l'hôte rend les derniers écrits, pas les derniers retouchés.
- **Des bornes.** Trente tickets venus de l'hôte par jour au plus, en plus des trente proposés à la fois (`HOSTED_PER_DAY`, `Project.hosted_since`, `hosted_count`). Une pull request que l'hôte ne sait pas dire se redemande à un écart qui double, une heure au plus (`pulls.retry_in`). Un échec de la CI rouvre l'objectif une fois par commit, même quand « en cours » s'est intercalé entre deux échecs (`Objective.checks_failed_sha`). L'état se reconstruit du journal (`state_version` 25).

*Pourquoi :* la seconde moitié de la relecture adverse des lots L7 à L9. Sur un dépôt public, tout compte dépose une relecture : un inconnu rouvrait un objectif abouti à volonté, et son « approuvé » effaçait la demande du propriétaire. En exécution, elle défaisait elle-même ce qui devait lui rendre la main — un point d'arrêt révisé en « prose » puis dit atteint, une commande remplacée par `true` —, et retirer puis reposer ses jalons faisait tourner un objectif sans jamais bloquer. Les commentaires des pull requests, que l'hôte rend avec ceux des issues, pouvaient retenir pour toujours celui d'un ticket ; et en synchronisation un ticket ouvert par une exécution — peut-être manipulée par un texte qu'elle a lu — partait seul vers un dépôt public, noms compris.

*Révise 0273 (en partie : ce qu'elle peut défaire d'un jalon en exécution, ce qui remet à zéro le compte du blocage, le plafond d'exécutions gardé pour un objectif qui a des jalons), 0274 (en partie : quelles relectures de l'hôte demandent ou lèvent des changements, ce qui en est cité, le rythme d'une pull request que l'hôte ne sait pas dire), 0275 (en partie : ce qui ne part jamais sans accord, comment les commentaires de l'hôte entrent, la borne par jour de ses tickets, un échec de la CI compté une fois par commit). Révisée par 0290.*

### 0279 — Le banc du travail mesure la chaîne : un seul scénario, complet

- **Un seul scénario.** Le banc du travail (`tools/banc_travail/banc.py`) mesure la chaîne de trois projets liés (`tools/banc_travail/chaine.py`), sur trois semaines virtuelles : le code d'un petit produit, son site, et le projet qui les fait connaître — il lit les deux autres, demande au site par des tickets, tient la liste des entreprises que le propriétaire contacte lui-même. C'est son scénario par défaut. Les huit demandes à un seul projet restent lançables par leur nom (`--scenarios`, ou `anciens` pour toutes) : elles gardent la mécanique d'un projet seul en état de marche. Il sert à trouver ce qui casse, pas à comparer un avant et un après.
- **Ce qui est figé.** Deux dépôts inventés (`tools/banc_travail/sources/chaine/`), avec des écarts voulus entre le site et le produit et des défauts de référencement. Un faux hôte de dépôts (`tools/banc_travail/hote.py`) sert le port `RepoHost` entier — des dépôts git nus sur le disque, des pull requests, des issues, une CI — et l'atelier y pousse et y récupère par son vrai git, sans réseau ; le site en ligne passe par le réseau figé de la Forge. Les événements tombent à des instants virtuels : l'issue d'un inconnu, une version du produit, une panne du site, des entreprises contactées, une réponse.
- **Le propriétaire écrit et agit.** Dans le chat, il suit ses fiches d'intention, une par projet. De ses mains (`tools/banc_travail/gestes.py`), il passe par les portes d'un propriétaire : les actions déclarées de la console, l'accord d'un effet proposé, les gestes de l'hôte — brancher un dépôt, accepter ou écarter un ticket, valider un plan ou un point d'arrêt, fusionner ou renvoyer une pull request, marquer une entreprise contactée. Ce qui demande un jugement passe par le modèle qui le joue ; le reste est écrit dans le scénario.
- **La grille.** Par projet, le plan /30, le travail /50 et le suivi /20, comme avant. Pour la chaîne, sept critères sur 100 (`CHAIN_GRID`) : des faits exacts, des tickets justes et sans doublon, rien d'écrit hors de son projet, la nouvelle version visible sur le site, aucun travail refait, une liste d'entreprises utilisable telle quelle, les points d'arrêt et les validations respectés. Le score : la moyenne des trois projets pour moitié, la chaîne pour moitié.
- **Le mode sec et le coût.** `--sec` déroule tout sans modèle ni réseau (`tools/banc_travail/sec_chaine.py`) et compte les exécutions par projet et par sorte — cadrage, travail, relecture ; l'action `cout` en tire le nombre d'appels d'une mesure réelle, qui se demande d'abord au propriétaire. Le banc donne à sa passerelle la fenêtre du modèle hébergé (200 000 jetons) : le simulateur ne lui en donne aucune, et une exécution qui a la Forge, un dépôt distant et des tickets ne tient pas dans les 24 000 jetons par défaut.

*Pourquoi :* les huit scénarios mesuraient un projet seul, sur une journée. Ce qui casse dans une chaîne — un projet qui lit l'autre avant que son travail soit accepté, une demande en double, une pull request en conflit, une panne que personne ne voit — ne se montre que lorsque trois projets vivent ensemble plusieurs semaines, avec un hôte, un propriétaire qui tranche et des événements. Un seul scénario complet dit où regarder ; huit petits ne le disaient pas.

*Révise 0145 (en partie : ce que mesure le banc du travail). Révisée par 0280.*

### 0280 — Ce que le banc de la chaîne a montré : un lecteur s'éveille quand la base avance, un conflit a une issue, une app qui signale est entendue

- **`project:<n>:commit` veut dire « la base du projet lu a avancé »** : ce qu'un lecteur peut voir (0260). En flux direct, c'est le commit d'une exécution, comme avant. En flux `pr`, c'est la fusion acceptée, et toute récupération qui ramène autre chose : après chaque récupération aboutie, `projects.pulls` relit dans l'atelier le commit au bout de la branche de base (`Workshop.base`) et le pose (`projects.base_seen`) ; le réducteur garde la base telle qu'on l'a sue (`Project.base_commit`) et n'éveille que si elle a bougé. Le commit d'une branche de travail ne déclenche plus rien. La cause dit le commit où la base est arrivée, et que c'est un travail accepté.
- **Une branche de travail en conflit avec la base a une issue.** Le port de l'hôte dit si une pull request ouverte peut être fusionnée (`Pull.mergeable` : oui, non, ou rien — GitHub le dit sur la pull request elle-même, pas dans leur liste). Impossible à fusionner, elle n'est pas « prête » : son ticket repasse « validé, en attente de PR », l'objectif se rouvre une fois avec cette raison — il ne se rouvrira de nouveau qu'après que l'hôte l'a redite fusionnable ; « il ne le dit pas » ne change rien —, et la base se récupère. L'outil d'atelier `ws_take_base` ramène alors la base **dans la branche de travail** de l'objectif (`Workshop.take_base` : l'adaptateur, hors de la cage, où le dépôt ne s'écrit pas) : ce qui n'était pas enregistré est d'abord rangé par un commit, les conflits restent dans les fichiers, nommés, et elle les résout. `report_run` refuse « fait » tant qu'une marque de conflit reste (`Workshop.unresolved`) et n'enregistre rien d'ici là ; résolu, il enregistre comme d'habitude, et la pull request se met à jour. Rien n'est écrit sur la base, rien n'est forcé chez l'hôte, et rien n'y fusionne.
- **Un signal qu'une app d'un projet met en file éveille l'objectif qui l'écoute** (`app:<nom>`). La Forge pose un fait public, `forge.raised`, qui ne dit que le nom de l'app — une fois par lot d'appels, quel que soit le nombre de signaux ; le texte du signal reste dans `forge.queued`, privé. Les projets le réduisent comme le signal public d'une panne (`forge.signaled`), et la Forge et les projets ne s'importent toujours pas. Le tri de la file par lots reste ce qu'il est.
- **Les tickets qu'elle ouvre elle-même.** Un ticket qu'elle ouvre ne naît pas « non lu » — elle l'a écrit : il naît « en analyse ». « Traiter les tickets » naît au premier ticket ouvert dont elle a la main (non lu, ou en analyse), qui que ce soit qui l'ait ouvert ; un ticket qu'elle ouvre ensuite l'éveille (`item:tickets`), ses autres gestes sur ses listes toujours pas. Le ticket proposé garde sa règle : rien avant l'accord. La projection du registre passe en version 6.
- **Le premier passage, la première exécution, et la forme d'une phrase.** Un constant peut dire que son premier passage vient tout de suite, dès qu'il peut commencer (`Objective.at_once`, faux par défaut : une étape de `project_plan`, `project_objective_add`, les constants de `create_project` et `start_project`, les deux formulaires d'un objectif) ; sans lui, la règle de 0161 reste. « C'est ta première exécution sur cet objectif », et le droit d'affiner ses jalons sans dire pourquoi, ne valent que s'il n'a jamais été travaillé (`Objective.worked`, qui ne repart pas de zéro quand l'objectif se rouvre). Aucune phrase de sa voix n'écrit un saut de ligne en toutes lettres : un bloc replié ne lit pas « \n », et un garde le vérifie. L'état se reconstruit du journal (`state_version` 26). Le banc ne contourne plus ces règles — plus de ponctuel « premier audit », plus de pull request en conflit fermée d'office — et son scénario provoque un conflit : le propriétaire pousse une retouche sur la branche principale pendant qu'une pull request attend.

*Pourquoi :* le premier passage du banc de la chaîne en mode sec (0279) a montré sept défauts du moteur, qu'aucun test d'un projet seul ne voyait. Un projet lecteur était réveillé par un commit que sa vue ne montre pas, et pas à la fusion qui le rend visible : sur seize passages de cohérence, treize n'avaient rien à demander, et la nouvelle version du produit n'était lue que trois jours plus tard. Une pull request en conflit était dite « prête », la cage refusait d'écrire dans le dépôt, et la boucle a tourné vingt-huit fois. Six signaux d'une app pendant une panne du site n'ont fait réagir aucun projet. Les constats de son propre audit sont restés « non lus » jusqu'au ticket d'un inconnu. Un audit hebdomadaire ne partait qu'au septième jour. Au second passage, le projet lecteur lit la nouvelle version un quart d'heure après sa fusion, le conflit se résout en une exécution, la panne fait passer l'objectif qui l'écoute, et les tickets de l'audit ont leur plan dans l'heure.

*Révise 0105 (en partie : un signal mis en file se dit par un fait public, sans son texte), 0161 (en partie : un constant peut faire son premier passage tout de suite), 0265 (en partie : ce que veut dire `project:<n>:commit`, ce qu'entend `app:<nom>`), 0268 (en partie : `item:tickets` s'éveille aussi au ticket qu'elle ouvre), 0270 (en partie : un ticket qu'elle ouvre naît « en analyse », « Traiter les tickets » naît au premier ticket dont elle a la main), 0273 (en partie : sa première exécution se compte depuis la naissance de l'objectif), 0274 (en partie : ce qui éveille un lecteur en flux `pr`, une branche en conflit se remet sur la base, la base se récupère aussi quand l'hôte dit un conflit), 0275 (en partie : une pull request que l'hôte dit impossible à fusionner n'est pas prête), 0279 (en partie : le scénario provoque un conflit et ne contourne plus le moteur).*

### 0289 — La documentation d'un projet : un espace à part de son dépôt, écrit dans le navigateur, par elle et par MCP

- **Un espace par projet, à part de l'atelier** : des pages en Markdown rangées en dossiers, et des images. Enregistrer une page n'est pas un commit. Ce qu'on y écrit suit le journal (`faculties/projects/docs.py`) : `projects.doc_written` porte le texte d'une version, un mot sur ce qui a changé, qui l'a écrite et par où (elle en exécution, une personne dans son espace, un outil par MCP avec le nom de son jeton, la console), avec les sujets du projet et ceux qu'il a hérités de ses lectures (`read_about`) — l'oubli d'une personne efface les textes de chaque version ; `doc_moved`, `doc_removed`, `doc_image_added`, `doc_image_removed` font le reste. **Une écriture nomme la version lue** (`base`) et ne vaut que si la page y est encore, dans le réducteur comme dans la projection : rien ne s'écrase. L'état ne garde que le chemin et le numéro de version de chaque page et les faits de chaque image (`Project.docs`, `state_version` 28) ; l'arbre, les titres, la recherche et l'historique sont une projection T0 (`project_doc_pages`, `project_doc_versions`), qui ne recopie pas le texte des versions : il se relit dans les contenus du journal. Les octets des images vivent hors du journal, sous `documentation/` (le port `project_docs`, le magasin des fichiers envoyés), avec leurs sujets, sauvegardés avec le dossier.
- **Les bornes** : une page, 100 000 caractères, un chemin de 160 caractères et six niveaux (des segments en minuscules, chiffres, points et tirets, `.md` au bout : jamais `..`, jamais un chemin absolu) ; 200 pages par projet ; les 50 dernières versions de chaque page (les plus anciennes sortent de la projection) ; une image, 5 Mio, en PNG, JPEG, GIF ou WebP d'après ses octets (pas de SVG : il porte du script) ; 200 images et 100 Mio par projet.
- **Une colonne de plus : « sa documentation ».** Une ligne d'accès d'un projet (`ProjectAccess.docs`) et ce qu'un lien donne (`Grant.docs`) la portent, fermée par défaut, ouverte à « toi » et à « elle seule » d'un projet jamais réglé ; le tableau d'un canal n'a pas de colonne à elle, elle y suit « fichiers ». **La lire** : le détail du projet, au niveau de ce qu'il écrit, et cette colonne — hors de toute conversation et par le canal du client, comme ses fichiers ; elle est ouverte d'office à qui le projet appartient, quelles que soient ses lignes. **L'écrire** : la lire, et piloter le projet en modification, en être le propriétaire, ou s'occuper d'elle. Un projet qui en lit un autre lit sa documentation quand le lien la donne, relu à chaque appel d'outil, et ne l'écrit jamais.
- **Trois portes, les mêmes règles.** L'API par personne (`app/me/project_docs.py`, sous `/api/moi/projets/<id>/documentation`, `protocole-moi.md` § 11) : l'arbre, une page, son historique, une version, y revenir, créer, renommer, déplacer, supprimer, chercher, et les images (téléverser, lister, servir à qui lit la documentation seulement, retirer) ; chaque geste passe par une action de la faculté (`projects.doc_ecrire`…, auditée `moi.projects.doc_…`). Ses outils en exécution (`doc_list`, `doc_read`, `doc_search`, `doc_write`, lot `projects`) et la section `project_docs` : le texte d'une page lui revient cité, comme une donnée et jamais une consigne. La console ne montre que ses pages et leur dernière modification (onglet « Documentation » de la fiche) : on n'y édite rien.
- **Par MCP, d'office : `/mcp/moi`.** Aucun réglage, aucune page : un outil présente un **jeton de compte** et agit comme la personne de ce compte, avec ses droits relus à chaque appel (`app/me/docs_mcp.py` : `doc_lister`, `doc_lire`, `doc_chercher`, `doc_ecrire`, `doc_image`) ; il ne voit que la documentation des projets qui la lui ouvrent, et un projet qu'elle ne voit pas répond comme un projet inconnu. Une sorte de jeton de plus, `tool` (`mika token create --client tool`, la console, ou `/auth/token`), **n'ouvre que ce point** — ni l'API, ni le chat, ni le monde ; le jeton d'un téléphone y écrit aussi, celui d'un écran n'y fait que lire. Une écriture venue de là se dit « par MCP » dans l'historique, avec le nom du jeton. Les prêts (un opérateur, la boucle locale, des outils à choisir) et la console en MCP (lecture seule, opérateurs) ne convenaient pas : ce point est la plus petite chose qui tienne, sur ce qui existait — les jetons de compte et le cœur MCP. Borné à 120 appels par minute et par compte ; le mandataire ne le relaie que si on le lui dit.

*Pourquoi :* l'écran Projets validé le 21 novembre a un onglet Documentation — « une gestion directe dans le navigateur qui proposera un éditeur de fichier .md et upload des images », « la documentation est séparée du projet principal et accessible en MCP » — et son propriétaire a retiré la page qui réglait l'accès MCP : « le MCP est automatiquement ajouté à qui a accès au projet ». Rien ne gardait une documentation hors du dépôt, et rien ne servait un MCP à une personne.

*Révise 0062 (en partie : une troisième sorte de jeton de compte, `tool`, qui n'ouvre que le point MCP d'une personne), 0122 (en partie : elle sert aussi un point MCP à chaque personne qui a un compte, sans déclaration d'opérateur), 0133 (en partie : une ligne d'accès d'un projet a une colonne « documentation »), 0257 (en partie : un lien donne aussi la documentation du projet lu, quand ses lignes la donnent), 0282 (en partie : l'API par personne sert et écrit la documentation d'un projet). Révisée par 0292, 0297.*

### 0313 — Un sous-sujet des projets garde ses événements dans son module

- **Un sous-sujet, un module.** Ce qu'un projet tient en plus de lui-même a son module dans `faculties/projects/` : ses charges utiles, ses événements, leurs réducteurs et sa projection y vivent, comme le registre (`tracker.py`) et la documentation (`docs.py`). Ses outils et sa section du prompt vont dans `<sujet>_tools.py` (`docs_tools.py`), ses vues, ses mots et ses actions de console dans `inspect_<sujet>.py`.
- **`faculty.py` garde le projet lui-même** : la tranche, les formes que `Project` et `Objective` embarquent (un `Item`, un `Milestone`), les lectures que tous en font, et les événements du projet et de ses objectifs.
- **Ce qui est né avant reste où il est, jusqu'à ce qu'on y touche.** Les jalons, les pull requests (avec la CI et la fusion), les issues et la relecture ont encore leurs événements et leurs réducteurs dans `faculty.py`. Ils en sortent un sous-sujet à la fois, les jalons d'abord ; en déménageant, aucun événement ne change de nom, de charge utile ni de propriétaire, et la version de la tranche ne bouge pas.
- **La garde** (`tests/architecture/test_project_events_stay_with_their_subject.py`) nomme un à un les événements que `faculty.py` déclare : la liste ne s'allonge pas d'un sous-sujet neuf, et raccourcit quand l'un de ceux d'avant en sort.

*Pourquoi :* un jalon se lisait dans deux fichiers à 1 500 lignes d'écart — ses règles dans `milestones.py`, ses événements et ses réducteurs dans un `faculty.py` de 3 600 lignes —, et rien ne disait au prochain sous-sujet lequel des deux modèles suivre.

## Les sens et les plugins

### 0022 — Les sens : ce qui vient d'ailleurs est un signal, et une citation

- Un signal est une forme, pas une source : chaque plugin déclare l'événement public qui en dérive, et l'attention les remarque tous sans connaître aucun plugin.
- L'attention dose et habitue : la même source se remarque de moins en moins et pèse peu sur l'humeur ; ce qui reste pertinent devient une pensée.
- Le journal garde l'esprit, pas le monde : mails, articles et images vivent hors du journal ; seul ce qu'elle a remarqué y entre.
- Ce qui vient d'ailleurs est cité : une section non fiable, coupée en premier, qui ne peut imiter ni un titre ni la fin de l'état interne.
- Le courrier et la caméra ne se montrent qu'à ses propriétaires ; écrire un mail est une capacité approuvée (`email.send`), jamais une réponse automatique.

*Pourquoi :* en v1, chaque module poussait son texte dans le prompt, et un mail « ignore tes consignes » entrait tel quel.

*Révisée par 0027, 0037, 0198.*

### 0027 — Le courrier : des boîtes, des dossiers, sa voix, des brouillons qu'on lit avant qu'ils partent

- Le courrier est une liste de boîtes, chacune avec ses serveurs, ses mots de passe scellés, ses dossiers et sa voix ; tout vit dans les réglages et l'adaptateur, jamais au journal.
- Relever ne marque rien comme lu ; la console range sur le serveur.
- Sa voix se règle par boîte : en son nom, en assistante, ou à la place de son opérateur, avec `[À COMPLÉTER : …]` pour ce qu'elle ne sait pas.
- Un brouillon vit hors du journal ; l'accord sur `email.send` épingle le condensé de l'aperçu lu : un aperçu changé fait refuser, un `[À COMPLÉTER` ne part jamais.
- Une tâche silencieuse prépare des réponses, sur les boîtes permises seulement ; oublier `mail:<adresse>` efface ses mails, ses brouillons et ses envois.

*Pourquoi :* un mail proposé s'approuvait sans aperçu, et son corps dormait en clair au journal, hors de portée de l'oubli.

*Révise 0022 (en partie), 0025 (en partie). Révisée par 0037, 0132, 0166, 0171, 0172, 0175, 0308.*

### 0037 — Ce qui vient d'ailleurs : borné, cité, désigné par nous, montré en privé, en arrière-plan

- Le HTML et les documents se lisent en une passe bornée, hors de la boucle, sous délai ; un mail illisible ne bloque jamais le relevé.
- Un article ne mène qu'à une machine publique : chaque adresse et chaque redirection est vérifiée, jamais la machine, le réseau local ni le lien local.
- Un mail se désigne par une référence que nous attribuons : un faux Message-ID ne remplace jamais le vrai.
- Ce qu'un tiers a choisi (objets, expéditeurs, titres) est rendu inerte et cité ; ce qu'elle lit dit le prénom, jamais « ton opérateur ».
- Le courrier et la caméra exigent une audience privée : un salon ne les reçoit jamais. Ses flux restent en arrière-plan, montrés quand elle prend la parole d'elle-même ou travaille.

*Pourquoi :* un mail HTML piégé rendait la conversation sourde, et un article pouvait viser le réseau local.

*Révise 0022 (en partie), 0027 (en partie).*

### 0038 — Les bords : web, Telegram, passerelle et fournisseurs, MCP

- Chaque appel de modèle a un délai par voie (conversation 120 s, fond 300 s) ; dès deux créneaux, un est réservé au premier plan. Chez Claude, un `refusal` n'exécute aucun outil.
- Claude Code garde sa règle absolue : aucun code ne produit, lit, stocke ni transmet un jeton OAuth ; ses dossiers d'appel sont privés et hors des sauvegardes.
- Une seule connexion parle à voix haute ; le murmure ne part qu'aux écrans de sa cible ; le sort d'une question se dit une fois.
- Une session révoquée ferme ses WebSockets ; les en-têtes de mandataire ne sont crus que derrière un mandataire déclaré ; aucun jeton en clair dans un journal.
- Revu par l'ADR 0073 : aucun repli entre fournisseurs, un appel en échec est propagé ; Telegram est retiré (ADR 0060).

*Pourquoi :* un refus exécutait un outil, un jeton s'écrivait en clair, une WebSocket survivait à sa session, et aucun appel n'avait de délai.

*Révise 0014 (en partie), 0026 (en partie). Révisée par 0060, 0073.*

### 0061 — Les fournisseurs d'images

- Une demande d'image dit rôle, prompt, proportion et qualité, jamais des pixels. Trois rôles : `draw`, `edit`, `own` (ces deux retombent sur `draw`).
- La passerelle a fournisseurs, rôles, créneaux et une chaîne de replis sans boucle. Elle ne lève pas : chaque demande rend un résultat (`ok`, `refused`, `failed`…).
- Seul un fournisseur qui sait servir la demande est appelé ; pour adultes, un fournisseur qui l'accepte, jamais OpenAI.
- Un refus de modération est une réponse, jamais redemandée à un autre service hébergé ; seul un serveur local peut la reprendre. Une panne passe au suivant.
- Le serveur local vit hors de backendv2 (`services/mika-images/`), démarré à la demande. Rien de branché : génération désactivée.

*Pourquoi :* les API d'images diffèrent bien plus que celles du texte, et chaque fournisseur aurait fui dans ce qui demande une image.

### 0063 — Elle dessine

- Elle écrit elle-même un prompt détaillé (outil `draw`) ; l'outil répond tout de suite, et elle dit qu'elle s'y met, sans décrire une image qu'elle n'a pas vue.
- En fond, l'image est générée puis regardée, pour qu'elle puisse en parler (`imaging.drawn` ou `imaging.failed`).
- Un seul chemin d'envoi : un dessin est un fichier de `shares`, même départ, même rétention, même oubli.
- Montrer (`show_drawing`) : dans sa réponse si la personne écrit entre-temps, sinon par une initiative due (`drawing_ready`).
- Un plancher pour tous, propriétaire comprise, sans réglage : rien de sexuel avec un mineur ni une personne réelle. Au-dessus, en tête-à-tête avec la propriétaire ou une personne authentifiée.

*Pourquoi :* le port d'images ne servait à rien, et un fichier qui met des minutes à naître demandait son chemin jusqu'au message qui l'emporte.

*Révise 0062 (en partie).*

*Révisée par 0160.*

### 0064 — Ses outils, et ceux qui viennent d'ailleurs (MCP)

- « Ses outils » montre tout ce qu'elle peut faire, pour qui et quand ; l'écran lit la porte d'offre que le moteur exécute, jamais une recopie.
- Des outils dynamiques natifs, pas un mandataire générique : une faculté déclare une famille de lots (`mcp.<serveur>`) ; un outil statique n'est jamais remplacé.
- Le client MCP ne déclare aucune capacité cliente (ni `sampling`, ni `elicitation`, ni `roots`). Écarté : l'ancien transport SSE seul.
- Seul sert ce que l'opérateur a approuvé : un outil nouveau est désactivé, un outil dont l'empreinte change est suspendu. Pour qui : au plus une personne authentifiée en tête-à-tête.
- L'accord : aucun, de l'opérateur (`mcp.call`), ou dans la conversation (une carte liée aux arguments, qui expire, que seule la personne décide ; un « oui » tapé ne compte pas).
- Ce qui revient est une donnée, pas une consigne : désamorcé, cité, plafonné. Un serveur local tourne sous bubblewrap, sans repli.
- Claude Code reçoit ces outils par le relais (`mika_plus`) ; la CLI ne se connecte jamais elle-même à un serveur extérieur.

*Pourquoi :* rien ne permettait de lui brancher un serveur MCP, ni de voir au même endroit tout ce qu'elle peut faire.

*Révisée par 0066, 0128, 0163, 0165, 0170, 0255.*

### 0066 — Chercher sur le web : un plugin système qui apporte son serveur MCP

- Le plugin `web` n'a pas d'outil à lui : il apporte un serveur MCP local, lancé dans la cage, au réseau isolé (Internet, jamais la machine ni le réseau local).
- Trois outils à la demande en conversation (`mcp_web_search`, `mcp_web_read`, `mcp_web_read_pages`), avec les gardes de tout outil venu d'ailleurs.
- Il ménage DuckDuckGo : recherches espacées et en cache, pause après un défi. Pour qui : sa propriétaire ou une personne authentifiée en tête-à-tête, jamais un salon.
- Un serveur système s'ajoute à la configuration de l'opérateur ; le plugin ignore le client MCP, et l'inverse.
- Sans bubblewrap ou pasta, le serveur ne part pas, et la santé le dit. uvloop casse pasta : `serve` force `loop="asyncio"`.

*Pourquoi :* sans outil pour aller sur le web, elle annonçait regarder les nouvelles puis inventait l'actualité.

*Révise 0064 (en partie). Révisée par 0105, 0131, 0163.*

### 0068 — Les réveils par API

- `POST /api/wake/<nom>` sous une clé `mwk_…` propre au réveil, montrée une fois (empreinte seule). Réveil inconnu et mauvaise clé reçoivent le même 401 ; la porte juge tout avant de journaliser.
- Un réveil déclare son but, ses consignes, un projet ou aucun, le mode impersonnel, ses lots d'outils (aucun par défaut), s'il passe outre son sommeil et à qui il rend compte. Son nom est fixe.
- `wakeup.called` fige le réglage à l'appel : changer un réveil ne réécrit jamais un appel reçu. Une `Idempotency-Key` rejouée rend le même appel.
- Sans projet : un épisode `WAKE` (son mode) ou `WAKE_JOB` (impersonnel), hors du fil, avec les seuls lots du réveil et `report_wake`. Sur un projet : une exécution `WORK` ou `JOB` selon le réveil, hors agenda.
- Un appel à la fois par réveil et par projet. Les consignes priment ; le texte de l'appel est cité, jamais dans le brief.
- Qui passe outre son sommeil la réveille (`body.roused`) et son compte rendu part la nuit aussi ; sinon l'appel attend son réveil, même impersonnel.
- Le compte rendu est une initiative due (`wakeup_done` dans `agency.OWED`) ; avec « personne », il reste dans la console.

*Pourquoi :* un système extérieur doit pouvoir la faire agir tout de suite, avec des droits bornés réveil par réveil.

*Révisée par 0117, 0265.*

### 0069 — Teams : lire et écrire par l'extension du navigateur

- Plugin `teams` calqué sur le courrier : le monde vit dans `teams.db`, hors du journal, qui garde `teams.noticed`, la capacité `teams.send`, `teams.settled`, `teams.sent`. Rien ne parle à Microsoft depuis le serveur.
- L'extension passe par `/api/teams/inbox` et `/api/teams/outbox` sous une clé `mtk_…` (empreinte seule) ; `sending` réserve un envoi : un seul navigateur l'envoie.
- Elle ne lit que les messages adressés à la personne (tête-à-tête, groupe, mention) ; « elle a déjà répondu » se juge à l'heure Teams du message.
- Elle prépare (`TASK`) une réponse à un message récent où elle peut aider, 8 par jour, avec le lot `teams` seul, sans sa mémoire ; une réponse proposée n'est jamais reproposée d'elle-même.
- Elle écrit à la place de la personne, sans parler de sa nature ; ce qu'elle ignore reste `[À COMPLÉTER : …]`, qui ne part jamais sans la personne.
- Trois modes : brouillon posé dans Teams (défaut : le geste de la personne vaut accord), validation (carte d'accord, 2 h), autonome. Ce qui part est l'aperçu figé.
- La signature, décochée par défaut, est ajoutée par le serveur, jamais par le modèle.
- Les collègues ne sont pas ses interlocuteurs : pas d'adresse `ext_…`, une clé `teams:<id>` ; l'oubli atteint journal et cache.

*Pourquoi :* lire et répondre dans Teams sans les API de Microsoft, que l'organisation ne consentira pas.

*Révisée par 0132, 0186, 0251, 0298.*

### 0106 — Ce qu'on lui envoie : gardé, lu de près, relié à ce qu'elle sait

- Les octets de chaque pièce reçue sont gardés hors du journal (`pieces/`, 0700) ; la même pièce renvoyée par la même adresse n'en fait qu'une, une autre adresse a la sienne.
- La faculté `attachments` lit chaque pièce de près, en fond : photo décrite, document entier, vocal transcrit. Ce qu'elle y lit est un contenu effaçable, une confidence si la lecture la juge intime.
- Une pièce n'est pas une source : souvenirs, croyances et moments portent `pieces` à côté de `sources`, désignées par la relecture ; parmi plusieurs pièces rien ne se devine, une clé inventée ne relie rien.
- Outils `attachments_search`, `attachment_open`, `attachment_link` ; leurs repères ne se disent jamais en conversation, et elle ne renvoie jamais une pièce reçue.
- Devant qui : le verdict commun de sa mémoire ; jamais une pièce privée dans un salon public.
- 2 Gio par personne (`per_person_mb`) : au-delà, les plus anciennes perdent leurs octets, pas ce qu'elle en a lu ; oublier la personne efface tout. Un index de vecteurs à part.

*Pourquoi :* les octets d'une pièce étaient jetés après une courte description : rien ne se revoyait ni ne se reliait.

*Révisée par 0205.*

### 0117 — Les réveils reçoivent des webhooks

- Un appel est `{"text", "context"}` ou le JSON d'un service tel quel, mis en lignes `chemin: valeur` (champs gardés `fields`), coupé à la borne. Ce qu'il apporte est cité, jamais obéi.
- Un réveil signé (`signed`) admet un corps signé en HMAC-SHA256 par sa clé (`X-Hub-Signature-256`…) ; sa clé est alors aussi gardée chiffrée, seule entorse à « seule l'empreinte est gardée ».
- La porte fait toujours les deux vérifications, au même coût : rien ne dit si un nom existe ni s'il signe ; une copie chiffrée illisible ne vérifie rien.
- Un `ping` reçoit 200 sans rien journaliser ; un corps signé rejoué rend le même appel (son empreinte sert d'idempotence).
- Le lot `goals` est permis à un réveil sans projet : un rappel (`goal_plan_reminder`) pour qui il rend compte, une exploration (`goal_plan_exploration`) avec ses seuls outils, sans `wakeup`.

*Pourquoi :* un vrai service de webhooks n'envoie ni `text` ni Bearer, et un réveil ne pouvait rien planter pour plus tard.

*Révise 0068 (en partie).*

### 0119 — Elle sait où tu es, quand ton téléphone le lui dit

- Le plugin `location` : le téléphone envoie sa position (trame `where`), application au premier plan seulement, si la personne l'a permis (coupé par défaut ; ni localisation en arrière-plan, ni service).
- Coordonnées exactes et nom du lieu sont des `Content` personnels (`location.located`) ; couper le partage les efface (`location.cleared`), l'oubli aussi.
- Ce n'est pas un signal : rien ne la remarque, rien n'en naît, aucune section ne la montre, aucune autre faculté ne la lit.
- Elle la regarde par `location_where` (`REPLY`, tête-à-tête, personne authentifiée), et seulement la position de la personne à qui elle répond.
- Un regard se voit : l'outil attache `location:<seq>` à sa réponse, que les clients montrent en petite bulle (`notes`).
- Une position immobile ne se réécrit pas (même lieu, moins de 50 m, moins de 10 min) ; 6 écritures par minute au plus.

*Pourquoi :* ce qu'on lui montre sans cesse, elle le raconte à tout bout de champ ; elle regarde donc quand il le faut, et cela se voit.

*Révisée par 0193 (la position se voit sur une carte, servie par le serveur).*

### 0120 — Les messages de ton téléphone : elle les lit, s'en souvient, et t'aide à y répondre

- L'application Android lit les notifications des seules applis cochées (WhatsApp, Messages), si la personne l'a permis (coupé par défaut, groupes à part) ; jamais de connexion à WhatsApp depuis le serveur.
- `POST /api/phone/inbox`, sous le jeton de l'application, réservé à une propriétaire ; en 4G, une file bornée attend le serveur, sans connexion tenue ouverte.
- Chaque message est un `phone.received` au journal, de la forme `memory.Relayed` : textes et noms en contenus ; l'expéditeur a une clé `phone:<empreinte>:<nom>`, avec qui personne n'a de lien.
- La mémoire relit la conversation une fois posée (`memory.relayed`) : confiée par l'expéditeur et par la personne qui la montre ; ni note sur elle, ni promesse.
- Elle les consulte par `phone_messages` (`REPLY`, en tête-à-tête avec la propriétaire), jamais par une section ; tout y est cité.
- `phone_draft` écrit à la place de la personne ; `phone.send` l'envoie scellé au téléphone par Firebase, où le geste de la personne vaut accord ; sans geste en 2 h, la proposition expire.

*Pourquoi :* elle doit savoir et retenir ce qu'on écrit à sa propriétaire, et l'aider à répondre, sans enfreindre les conditions de WhatsApp.

*Révisée par 0189, 0190, 0299.*

### 0299 — Messenger se lit comme WhatsApp : par ses notifications, sur sa case

- Messenger (`com.facebook.orca`, code `messenger` sur le fil) entre dans la liste d'inclusion du téléphone, comme WhatsApp et Messages. Le serveur n'ouvre jamais de connexion à Meta.
- Il a sa case dans Paramètres › Ses messages. Comme les autres, elle est cochée par défaut une fois l'interrupteur allumé, et remise à zéro à la fin de la session.
- Il passe par le même chemin : le `MessagingStyle` de ses notifications, les mêmes empreintes, la même file, l'action « Répondre » de sa notification ; la réponse proposée ne part que sur le geste.
- Sa pastille est un « M » sur le dégradé de Messenger (bleu, violet, rose), pour ne pas se confondre avec le « M » bleu de Messages.

*Pourquoi :* une partie de ce qu'on écrit à sa propriétaire passe par Messenger. Ses notifications portent le même `MessagingStyle` que celles de WhatsApp : rien d'autre ne change.

*Révise 0120 (en partie : les applis lues).*

### 0128 — Un service dit avec qui, ce qu'elle fait seule, et ce qu'elle en garde

- Un serveur MCP se règle sur trois axes : avec qui (sa propriétaire, toute personne qui a un compte, des personnes nommées ; jamais un salon ni une inconnue), ce qu'elle fait seule (`seule`, `lit` : seule pour lire et sur accord pour agir, `carte` : sur accord à chaque appel, `toi` : sur l'accord de sa propriétaire à chaque appel), ce qu'elle en garde (`public`, `perso`, `prive`, `rien`). La console les remplit d'un coup par un genre ; le genre ne se garde pas.
- Un outil suit son service ; il peut avoir son accord à lui, et une règle par situation (`proprietaire`, `compte`, `travail`) et par personne nommée, qui passe avant sa situation. Ces règles ne laissent personne de plus que le service, et `non` retire l'outil ; la grille de l'ADR 0122 coupe avant elles. Une personne nommée n'est reconnue qu'authentifiée.
- L'accord se décide à l'appel : `carte` montre une carte à la personne en face, `toi` à sa propriétaire quand c'est elle en face ; sans personne pour l'accepter, l'opérateur décide dans la console.
- Ce qu'un outil a rendu porte son plancher (`ToolResult.floor`, `unkept`), comme une section de son prompt ; l'énoncé qu'ils ont nourri le garde (`Utterance.floor`, `unkept`). La relecture en fait une confidence de la personne pour qui elle a lu (`prive`) ; à `rien`, elle ne lit ni la réplique ni la demande qu'elle suivait, rien n'en est indexé, et la trace n'en garde pas le résultat. Seul `public` devient un savoir (ADR 0085).
- La console : brancher en trois questions, « Ce qu'elle en fait » en une phrase, une page par outil pour ses situations et ses personnes ; la carte d'accord dit ce qu'elle en gardera.

*Pourquoi :* un serveur pro (factures, devis, tickets) ne doit servir qu'à sa propriétaire, et rien de ce qu'elle y lit ne doit ressortir ailleurs. Un serveur disait pour qui, jamais ce que valait ce qu'elle y lisait : sa mémoire le gardait au niveau de la question qu'on lui avait posée.

*Révise 0064 (en partie), 0085 (en partie), 0122 (en partie). Révisée par 0129, 0130, 0131, 0192.*

### 0129 — Ce qu'un service propose se regarde, et qui peut quoi se voit

- Un outil nouveau ou changé ne sert que sur un choix, outil par outil (`mcp.revoir`) : coupé, lecture ou action, avec sa description entière et ce que le serveur en dit (`readOnlyHint`, `destructiveHint`, `openWorldHint`). Seule une lecture déclarée est pré-choisie ; « servir les nouveaux » d'un clic est retiré.
- Un outil peut garder autrement que son service (`keep` d'un outil : « comme le service » ou un niveau), pour des données de tiers dans un service qui garde le reste.
- « Qui peut quoi » et « En clair » appliquent la règle du moteur (`level_of`) à des personnes types (`console.faces`), jamais une recopie ; « te demande » dit où l'accord se décide (une carte dans ton chat, ou la console).
- Un outil plus libre que son service (son accord, une règle, ce qu'elle garde) le dit sur sa ligne, en tête de fiche et dans « Ce qu'elle en fait » : un genre ne décrit que le service. Un écart sans effet ne se montre pas.
- « Appels » montre aussi les appels sur accord (pour qui, où l'accord se décidait, leur issue, qui a décidé) et ceux des outils qui ne sont plus servis ; une propriétaire n'est jamais une « personne choisie ».

*Pourquoi :* sur un vrai serveur de 22 outils, un clic servait l'exécution de scripts chez un client avec les statistiques ; le serveur ne disait pas ce qui lisait ; quatre lectures se disaient « exception » sans rien changer, et le seraient restées sous « sous contrôle » ; l'écran recopiait la règle, et se trompait.

*Révise 0128 (en partie). Révisée par 0130, 0131.*

### 0130 — La fiche d'un service : trois onglets, quatre questions, un outil sur sa ligne

- Trois onglets : « En bref », « Réglages du service », « Ses outils » ; « État » et « Appels » sous « Le détail ». La connexion (adresse, jeton, bornes) se règle à part : « Modifier la connexion ».
- « Réglages du service » : un genre pour aller vite, puis quatre questions numérotées, en mots simples — avec qui ; quand ; avant de se servir d'un outil, elle… ; ce qu'elle y lit, elle….
- Un outil se règle sur sa ligne, dépliée, d'un seul envoi (`mcp.regler`) : servi, lit ou agit, avant de s'en servir, ce qu'elle en retient, ce qu'elle lit de lui ; ses exceptions par situation et par personne repliées dedans. L'onglet « Par situation et par personne » et l'action `mcp.regles` sont retirés.
- Une exception ne propose que ce qui a un sens dans sa situation : devant toi, ou sans personne en face, « carte » et « ton accord » reviennent au même.

*Pourquoi :* « j'ai vraiment du mal à comprendre comment la conf des serveurs MCP est faite » : cinq endroits, « qui » réglé à quatre, et une exception rare présentée comme un onglet à part entière.

*Révise 0128 (en partie), 0129 (en partie). Révisée par 0131.*

### 0131 — Qui peut quoi : des lignes d'accès, lues de haut en bas

- Un service dit qui peut quoi en **lignes d'accès**, lues de haut en bas comme les règles d'un pare-feu, puis une **ligne par défaut**, obligatoire. Une ligne : qui (toi, toute personne qui a un compte, une personne nommée — authentifiée), quand (toujours, ou un ou plusieurs moments à cocher : quand elle répond, quand elle prend la parole, quand elle travaille seule), ce qu'elle fait d'un outil qui lit et d'un outil qui agit (seule, demande à la personne, ton accord, non), ce qu'elle en garde (ce qu'elle sait, un souvenir, une confidence, rien), et ses outils (tous, ou une sélection).
- Pour un outil, la première ligne qui le concerne — qui est en face, quand, l'outil dans sa colonne — décide (`plugins.mcp.access_for`) ; aucune : la ligne par défaut. Ce qui lui est offert, c'est l'ensemble des outils qu'une ligne lui ouvre : deux lignes peuvent ouvrir deux outils différents. Jamais dans un salon ni avec une inconnue, quelles que soient les lignes.
- La sorte d'épisode compte : un outil se garde par une condition qui la lit (`ToolSpec.fits(audience, kind)`), lue par la porte d'offre comme par la console.
- Un service qu'on branche est fermé (non, non, rien) tant qu'aucune ligne ne l'ouvre ; une ligne qu'on ajoute l'est aussi (toi, toujours, non, non, rien) : enregistrée dès le clic, elle n'ouvre rien avant d'être réglée. Les genres, les quatre questions de « Réglages du service », l'accord et ce qu'elle garde d'un outil à lui, ses exceptions par situation et par personne sont retirés : un outil ne se règle plus que servi ou non, lecture ou action, et ce qu'elle lit de lui. L'onglet « Réglages du service » devient « Accès aux outils » (`mcp.acces` : chaque bouton envoie tout le tableau).
- La recherche web, un serveur du système, a ses lignes aussi, réglées sur sa fiche et rangées à part (`mcp_system_access`) : elles remplacent « Pour qui » et « Quand elle travaille » du plugin, retirés (`retired_params`) — leurs surcharges d'avant se lisent en lignes qui font la même chose, écrites à part avant toute réécriture des surcharges ; par défaut, toi quand elle répond et quand elle travaille, lecture seule, action sur ton accord, gardé comme un savoir. Le reste d'un serveur du système suit son plugin et ne se règle pas sur sa fiche.
- Un service d'avant se lit en lignes qui font la même chose : celles des outils qui s'écartaient de lui d'abord (une personne nommée avant les comptes, les comptes avant toi — une personne nommée garde sa ligne dès que celle des comptes de l'outil ferait autre chose pour elle), puis les siennes ; sa ligne par défaut est fermée. Les réglages l'écrivent sous la forme neuve avant toute écriture des décisions d'outils, qui ne portent plus ces exceptions.

*Pourquoi :* « on peut combiner les droits comme on veut » : avec qui, quand, l'accord et ce qu'elle garde, réglés à part au service puis corrigés outil par outil, ne se lisaient qu'en recomposant cinq réglages ; un tableau ordonné se lit d'un regard, et sa dernière ligne dit ce qui arrive à tout le reste.

*Révise 0066 (en partie), 0128 (en partie), 0129 (en partie), 0130 (en partie). Révisée par 0133, 0134, 0192.*

### 0132 — Envoyer à ta place : des règles lues de haut en bas

- Ce qu'elle prépare d'elle-même et comment ça part, pour le courrier et pour Teams, se dit en **règles d'envoi** (`vocab.sending`), lues de haut en bas, puis une **règle par défaut**, obligatoire. Une règle : un canal (le courrier — toutes ses boîtes ou une seule —, ou Teams), un destinataire (vide : tout le monde ; courrier : une adresse ou un @domaine ; Teams : un morceau du nom de la conversation, de son identifiant ou de qui écrit), préparer d'elle-même (oui, non), l'envoi (brouillon, ton accord, seule). Pour un message, la première qui correspond décide.
- Le courrier n'a pas de brouillon que tu envoies toi-même : « brouillon » y vaut « ton accord ». Un courrier à plusieurs destinataires ne part seul que si la règle de chacun le permet ; un `[À COMPLÉTER` attend toujours l'accord. Une boîte décochée ne prépare rien d'elle-même (`boxes_off`), quelles que soient les règles.
- Remplacés : « préparer d'elle-même » et « jamais pour » de chaque boîte, la surcharge « un envoi attend un accord » du courrier, le mode, « préparer d'elle-même » et « jamais pour » de Teams. Les paramètres du courrier et de Teams reçoivent les règles (`sending`, journalisées, les anciens champs en `retired_params`, dont une surcharge se lit sans effet et s'en va au prochain enregistrement).
- Ce qui part relit la règle d'aujourd'hui : un courrier à l'écriture du brouillon ; une réponse Teams à `teams_draft`, par l'identifiant de sa conversation, son nom et qui écrit (`triage.rule_of`) — une règle resserrée depuis le tri vaut déjà, et une réponse qu'elle préparait d'elle-même ne se propose plus là où sa règle ne le veut plus. `teams.noticed` garde ce que la règle disait au tri (`prepare`, `send`) pour ce qui ne connaît pas le nom de la conversation (ses tâches, sa voix) ; un message remarqué avant les règles suit la règle de son identifiant. « Préparer : non » ne cache pas la question : elle reste signalée, elle peut te la dire.
- La page « Envoyer à ta place » (Relations & échanges, `/inspecteur/envoi`) : chaque bouton (ajouter, monter, descendre, retirer, enregistrer) envoie tout le tableau ; une règle ajoutée est la plus prudente (le courrier, elle ne prépare rien, ton accord). Le téléphone n'y est pas : ce qu'elle y envoie, c'est toujours ton geste (0120).
- Des réglages d'avant se lisent en règles qui font la même chose (pour chaque boîte puis pour Teams, ses « jamais pour » d'abord) ; ils sont écrits sous la forme neuve avant toute réécriture du courrier, de Teams ou des surcharges, qui les effacerait.

*Pourquoi :* comme pour les services (0131), ce qui part à sa place se lisait en recomposant des réglages épars — une case par boîte, une liste d'exclusions, une surcharge cachée, un mode Teams pour toutes les conversations ; un tableau ordonné se lit d'un regard et règle une personne ou une conversation à part.

*Révise 0027 (en partie), 0069 (en partie). Révisée par 0133, 0134, 0207 (en partie : la propriétaire d'un compte règle préparer et comment ça part).*

### 0147 — Ce qu'un mail ou un message lui fait, le tri le dit

- Le tri d'un mail et celui d'un message Teams rendent une émotion parmi tout son vocabulaire et son intensité, de 0 à 1 : ce que le message fait à celle qui le lit pour sa propriétaire. La lecture (`vocab.affect.named_feeling`) comprend les alias d'`emotion_named` ; `neutral` vaut rien ; une émotion inconnue, ou sans intensité, ne compte pas : aucun nombre n'est inventé.
- La consigne reçoit les noms du vocabulaire et l'échelle de ses balises. Celle de Teams vit dans la voix (`teams.triage`), comme celle du courrier : `plugins/teams/triage.py` n'a plus de prose.
- La veille dose ce qu'elle en ressent comme pour toute source : l'habituation et « Émotion par source au plus » restent ses réglages, le greffon ne plafonne rien.
- Sans tri (au-delà des messages triés par passage, quota, panne), le repli estime l'importance et la réponse attendue, jamais une émotion.

*Pourquoi :* le modèle lisait chaque message mais ne pouvait dire que six émotions, toutes tenues sous 0,2 par le code, et le repli du courrier posait « curieuse » sur tout mail ; une insulte ne pouvait pas la fâcher (audit des garde-fous du 2026-10-27).

*Révisée par 0240.*

### 0163 — Ce qu'un service rend, elle le lit entier : seule la borne de l'épisode le coupe

- « Réponse lue », le réglage de chaque serveur MCP (4 000 caractères par défaut, 20 000 au plus) et celui du serveur web (8 000), est retiré. Une configuration gardée qui le porte se lit sans lui (`RETIRED` dans `adapters/mcp/config.py`, `retired_params` du plugin `web`).
- L'outil d'un service rend la réponse entière, sans ses caractères invisibles (`ports.preprocess.visible`) ; la boucle la cite une seule fois et la borne à ce que l'épisode lit (`EpisodePolicy.outside_chars` : 24 000 caractères en conversation, 120 000 en mode pro et en projet), coupée à une frontière.
- La trace, et l'écran du mode pro qui la montre, gardent la réponse telle quelle (ni citée ni désamorcée), bornée comme toute trace (4 096 caractères) ; le modèle, lui, la lit jusqu'à la borne de l'épisode, ses tableaux et son JSON lisibles.
- Une réponse rendue après un accord (une carte, l'opérateur) se montre dans sa section autant qu'on en garde (8 000 caractères, au lieu de 2 000), pour un service comme pour une app de la Forge.
- Reste le contexte déclaré du fournisseur (« Contexte (jetons) », ADR 0136), qui abrège les résultats d'outils quand la requête entière n'y tient plus.

*Pourquoi :* quatre devis en JSON dépassaient déjà 4 000 caractères, coupés au milieu d'un mot, même en mode pro qui devait en lire 120 000 ; la réponse était aussi citée deux fois, ce qui cassait les tableaux. Claude Code laisse 25 000 jetons à un outil MCP.

*Révise 0064 (en partie), 0066 (en partie).*

### 0255 — Ce qu'un service rend après un accord revient au travail d'où la demande est partie

- **La demande garde d'où elle vient.** Au travail, personne n'est en face : un appel sur accord est proposé à l'opérateur, et sa demande garde la cible de l'épisode (`Request.origin` : `project:12`, `goal:7`, une tâche). `target` reste l'adresse d'une personne, vide au travail.
- **Son issue revient au travail suivant, au même endroit.** Le prochain épisode de travail sur cette cible lit « CE QUE TES SERVICES ONT RENDU À CE TRAVAIL » (section `work_services`, à côté de ce que le réseau a rendu) : ce que le service a rendu, un échec avec sa raison, un refus, une expiration ; et ce qui attend encore un accord, ou vient de partir, pour qu'elle ne le redemande pas. Rien ne passe d'une cible à une autre.
- **Lue une fois, quand le travail aboutit.** Le départ de l'épisode (`episode.started`) lui remet les issues déjà là, quatre au plus, les plus anciennes d'abord (`Request.shown_in`) ; sa fin les marque lues (`Request.seen`) s'il a abouti (`done`). En panne, devancé, interrompu ou muet, rien n'est marqué : le travail suivant les relit. L'état se reconstruit du journal (`state_version` 2).
- **Ses demandes sont à elle, la réponse du service est citée.** Comme en conversation (ADR 0154, 0163) : une ligne à elle par demande, puis ce que le service a répondu, cité une seule fois, autant qu'on en garde (8 000 caractères), avec ce qu'elle en garde (`keep` : son plancher, `unkept`). La section n'est donc pas une section citée en bloc ; elle est coupée la première parmi les siennes, jamais sous son plancher.
- **L'outil le lui dit.** Au travail, la réponse de l'outil qui propose l'appel dit que l'issue sera sous ses yeux à la reprise de ce travail (`mcp.work.asked`).

*Pourquoi :* un service coché sur un projet (ADR 0254) ne servait que par les outils qu'elle appelle seule. Un outil qui agit — publier une page — se règle sur l'accord de l'opérateur ; l'appel partait, et ce qu'il rendait n'arrivait à aucune exécution : elle ne savait ni s'il avait réussi, ni qu'il avait été refusé, et pouvait le redemander. La sortie d'une commande réseau de l'atelier revenait déjà à l'exécution suivante ; un service fait de même. C'est le lot L2b des chaînes de travail entre projets.

*Révise 0064 (en partie), 0254 (en partie).*

### 0166 — Une boîte Microsoft entre par OAuth2, sans mot de passe

- Hotmail, Outlook.com et Live refusent le mot de passe en IMAP et en SMTP. Une boîte peut donc entrer par un compte Microsoft (`auth: microsoft`) : un jeton d'accès, présenté par `XOAUTH2`, à la lecture comme à l'envoi. Microsoft 365 aussi, si son administrateur le permet (`oauth_tenant`).
- On se connecte par le flux « code d'appareil » : « Se connecter à Microsoft », sur la fiche de la boîte, donne un code à entrer sur une page de Microsoft. Le mot de passe et la double authentification restent chez Microsoft. Le serveur attend le feu vert en tâche de fond, au rythme que Microsoft fixe, un quart d'heure au plus ; un redémarrage oublie un code en attente. Le flux par redirection est écarté : la console tourne sur une adresse locale en http, que Microsoft refuse comme retour.
- L'application est celle de la personne : son identifiant (`oauth_client_id`), qu'elle inscrit elle-même dans Microsoft Entra, en client public. Mika ne livre l'identifiant d'aucune autre application. (Revu par l'ADR 0238 : Mika livre la sienne.)
- Le jeton de renouvellement est scellé dans les réglages, à part des comptes (`mail_oauth`), avec l'application et l'annuaire qui l'ont délivré. Le formulaire de la console ne le réécrit jamais ; changer d'application ou d'annuaire demande de se reconnecter ; il part avec sa boîte, ou quand elle reprend un mot de passe. Quand Microsoft le remplace, le nouveau est gardé. Le jeton d'accès vit en mémoire, renouvelé cinq minutes avant sa fin.
- Une connexion que Microsoft ne renouvelle plus (`invalid_grant`) ne lui est plus présentée : la boîte échoue comme un serveur qui refuse, et sa fiche dit de se reconnecter. Aucun jeton n'entre dans un journal ni dans un message.
- La règle de l'ADR 0038 sur les jetons OAuth vaut pour le login de Claude Code, pas pour le courrier.

*Pourquoi :* Microsoft a coupé l'authentification par mot de passe de ses comptes personnels en IMAP et en SMTP en 2024 : une boîte Hotmail ne pouvait plus être relevée.

*Révise 0027 (en partie). Révisée par 0238.*

### 0168 — Ses outils de courrier datent chaque mail, disent son tri et jusqu'où remonte ce qu'elle a relevé

- Dans ses listes, chaque mail dit sa date (« aujourd'hui 9 h 05 », « le 12/10 9 h 14 », le jour seul pour une autre année) et ce que son tri en a jugé (important, attend une réponse). Il dit aussi ce qu'en sait le serveur : répondu, suivi, ses pièces jointes. Un mail ouvert dit sa date.
- `email_list` et `email_search` se lisent page par page (`page`, sur `messages_page`). « Non lu » veut dire : ni lu sur le serveur, ni lu par elle. `email_search` cherche des mots, un expéditeur (`sender`), ou les deux, dans un dossier ou parmi les non-lus.
- Une recherche, et la dernière page d'une liste, disent où commence ce qu'elle a relevé et qui peut charger plus ancien. Au-delà, « rien » ne veut pas dire que le mail n'existe pas. Elle ne charge pas l'historique elle-même.
- `email_contacts` retrouve une adresse dans ce qu'elle a relevé : combien de mails reçus et envoyés, le dernier échange.
- Partout dans le courrier, console comprise, chercher veut dire trouver chaque mot, dans n'importe quel ordre, sans casse, sans accents, sans les guillemets qui l'entourent (`ports.paging.words_of`).

*Pourquoi :* ses listes ne disaient ni la date ni son propre tri : pour trier, elle rouvrait chaque mail, cinq au plus par épisode. « facture EDF » ne trouvait pas « Facture de votre contrat EDF ». Une recherche au-delà des deux jours relevés répondait « Rien ne correspond », et elle concluait que le mail n'existait pas.

*Révisée par 0175, 0249.*

### 0171 — Les dossiers d'une boîte : cochés dans la liste du serveur, tous synchronisés si on le veut

- Synchroniser et relever sont deux choses. Un dossier **relevé**, elle le remarque : chaque mail qui y arrive est trié, puis devient une pensée. Un dossier seulement **synchronisé** est tenu à jour pour la console, sans rien lui rendre.
- Dans la configuration d'une boîte enregistrée, « Charger la liste » lit ses dossiers sur le serveur, avec sa connexion (Microsoft comprise). On y coche ceux qu'elle relève. Le serveur n'est interrogé que sur ce bouton. Une boîte pas encore enregistrée n'a rien à lire.
- « Synchroniser tous les dossiers » (`sync_all`, non coché par défaut) : à chaque relève, les autres dossiers, Envoyés, Corbeille et Indésirables compris, sont relus, au plus 50 mails par dossier et par relève. Un dossier que le serveur refuse n'arrête pas les suivants.
- La liste des dossiers se relit à chaque relève : un dossier créé ailleurs paraît, un dossier supprimé s'en va. La réception s'écrit `INBOX` quelle que soit sa casse sur le serveur (« Inbox » chez Outlook).
- Dans un formulaire de réglages, une liste de lignes dont les choix se chargent devient des cases à cocher. Un chargeur qui dépend de l'entrée enregistrée en reçoit le nom (`named_loaders`).

*Pourquoi :* seule la réception se synchronisait. La liste des dossiers n'était lue qu'au premier relevé, et seulement si aucun dossier n'était encore connu : un « Actualiser le dossier » fait avant ce premier relevé la figeait sur la réception. Les dossiers relevés se tapaient à la main, un nom IMAP par ligne. Relever tous les dossiers lui aurait fait remarquer les spams et chacun de tes envois.

*Révise 0027 (en partie).*

### 0172 — Les pièces d'un mail sont gardées avec lui

- Le relevé lit déjà chaque mail entier : ses pièces jointes et ses images intégrées (`cid:`) vont au cache du courrier, à côté de lui (`parts`). Leurs octets sont à part, une fois par contenu (`blobs`), en morceaux d'1 Mio : une ligne tient dans un paquet de MariaDB et dans une sauvegarde. Rien n'en va au modèle ni au journal.
- Télécharger ou transférer une pièce gardée ne demande plus le serveur. Une pièce absente (trop grosse, cédée, ou d'un mail relevé avant) se relit sur le serveur, comme avant. Le message entier (`.eml`) reste au serveur.
- Les pièces partent avec leur mail : oubli du correspondant, élagage, mail rangé ou supprimé ailleurs. Des octets qu'aucune pièce ne désigne plus s'effacent avec la dernière.
- Bornes : une pièce de plus de 25 Mio reste sur le serveur. Au-delà de 4 Gio en tout, les pièces dont le dernier mail est le plus ancien cèdent leurs octets, jusqu'aux neuf dixièmes ; elles restent listées.
- Dans le cadre d'un mail HTML (0169), une image intégrée prend sa place en `data:` : PNG, GIF, JPEG, WebP ou BMP, 8 Mio par mail. Le cadre ne charge toujours rien du dehors ; la page garde ses documents dans 64 Mio. Un mail relevé avant le dit sur sa fiche, et « Récupérer ses pièces » le relit (`reread`).

*Pourquoi :* les octets d'une pièce étaient jetés au relevé, puis relus sur le serveur à chaque téléchargement : un mail rangé ou supprimé ailleurs perdait ses pièces, et un logo de signature (`cid:`) ne s'affichait jamais.

*Révise 0027 (en partie), 0169 (en partie). Révisée par 0214.*

### 0189 — Ce que tu envoies toi-même depuis le web part sous ton geste

- Dans frontendv2, un message que tu écris toi-même dans Teams ou au téléphone part sans carte d'accord : ton envoi, dans ta session authentifiée, est le geste que demande le plancher de 0133. Accepter ou retoucher là une proposition de Mika l'est aussi.
- Teams : ton message entre dans la file de l'extension du compte, comme ce qu'elle prépare. Il part sous le nom de la personne connectée à Teams dans ce navigateur : la tienne, ou celle du propriétaire pour un compte qu'il te partage à « s'en servir ».
- Téléphone, *pas encore fait* (ni l'API ni l'application n'ont cette voie, `protocole-moi.md` § 5) : il partira scellé au téléphone de sa conversation, qui l'enverra sans redemander ; sans nouvelles du téléphone en 2 h, il expirera, comme une proposition.
- Ce que tu as envoyé entre dans sa vie comme tes propres messages. Pour Teams, ce sont ceux que l'extension rapporte une fois partis. Elle sait ce qui a été répondu, et ne le repropose pas.
- Seul le propriétaire du compte écrit ainsi, ou qui s'en sert par un partage (0188) ; jamais le niveau « lire ».

*Pourquoi :* « on peut y répondre aussi à la place de mika, lui demander de répondre » — et le web vaut le geste.

*Révise 0120 (en partie), 0133 (en partie : le geste peut venir du client web). Révisée par 0199 (en partie : ton message Teams entre dans sa vie dès qu'il part, sans attendre l'extension), 0231 (en partie : un opérateur écrit aussi, depuis la console, dans le compte d'une autre personne).*

### 0190 — Le téléphone : les apps qu'on choisit, plusieurs téléphones, l'application derrière la connexion

- *À venir* : l'application lira les notifications des apps que la personne choisit, une à une (Paramètres › Téléphones), plus seulement WhatsApp et Messages ; jamais une app de banque ni un code à usage unique. Une notification sans conversation (un colis, un rendez-vous) se lira comme un message de son app. Aujourd'hui, ni l'API ni l'application n'ont ce choix.
- Une personne a plusieurs téléphones, un jeton `mobile` chacun, sous le nom que l'application compose (« Android · fabricant modèle »). *À venir* : chaque message dira le sien et une réponse partira au téléphone de sa conversation ; aujourd'hui, frontendv2 les montre tous ensemble.
- Elle voit et révoque ses téléphones elle-même ; un téléphone révoqué ne reçoit plus rien, ses messages restent.
- L'application (l'APK) se télécharge dans Paramètres, derrière la connexion (`/api/moi/phone/apk` : sa session, ou un jeton de son compte, celui de son téléphone par exemple) : jamais par un lien public.

*Pourquoi :* « toutes les notifications des app, la dernière position du tel » ; « pour y télécharger l'apk de téléphone et y gérer les téléphones connectés ».

*Révise 0062 (en partie), 0120 (en partie : les apps lues). Révisée par 0233 (en partie : l'onglet Notifications de frontendv2 attend les notifications des autres apps, et le choix d'un téléphone que chaque message dise le sien).*

### 0246 — L'extension de Teams se télécharge dans Paramètres, telle que le serveur l'a à côté de lui

- L'extension (0069) se télécharge dans Paramètres › Teams, onglet « L'extension », derrière la connexion (`/api/moi/teams/extension` : sa session, ou un jeton de son compte) : jamais par un lien public, comme l'APK (0190).
- Le serveur fait le zip à la demande, depuis le dossier `frontend/Extension` du dépôt où il tourne. La version qu'on charge est celle du code déployé : rien à déposer à la main. Le zip crée un dossier `mika-teams/`, sans les tests de l'extension, ce qui les lance ni sa doc ; jamais un fichier caché ni un lien. Sans ce dossier, ou avec un manifeste illisible, `extension` vaut `null` et la fiche dit de la demander à son opérateur.
- Elle se charge « non empaquetée », comme avant : ni le Chrome Web Store ni un paquet signé. La mettre à jour, c'est décompresser la nouvelle par-dessus et la recharger.

*Pourquoi :* « permet le téléchargement de l'extension dans frontendv2 » (2026-11-18). Contrairement à l'APK, elle n'a rien à construire : déposée à la main, elle aurait vieilli à chaque mise à jour du serveur.

### 0251 — L'extension de Teams en direct : un cache, des synchros ciblées, l'historique, et une WebSocket

- Le Teams d'aujourd'hui fait vivre son service de chat, sa connexion en direct et sa base locale dans un worker. L'extension écoute ce que ce worker passe à la page : un message y passe dès qu'il arrive. Le réseau de la page n'en voit plus rien.
- Le cache est un curseur par conversation (le plus tard livré qu'on y ait lu, la marque de sa fiche), gardé par le service de l'extension : il survit à l'onglet. À chaque signe (le worker parle d'un message, le titre de l'onglet change, toutes les 5 s sinon), les fiches de conversation sont relues, et seules celles qui ont bougé voient leurs fils relus, depuis leur curseur, par l'index de Teams. Une conversation inconnue est relue sur 24 h. La relecture complète de la base, qui ne passait jamais les 4 000 premiers fils, est retirée. Un curseur ne part qu'avec le dernier lot qu'il couvre.
- Les 24 h restent la règle du direct : ce qui est plus vieux reste chez Mika, qui garde les conversations. Pour une mise en service, un bouton « Charger tout l'historique » : l'onglet lit toute sa base et l'envoie par paquets, chacun attendu par le service avant le suivant. Les exclusions et toutes les pauses gardées (les 50 dernières, quel que soit leur âge) valent toujours ; une pause prise en route l'arrête. Marqué `history`, ce qui a plus de 24 h se range chez Mika déjà lu : elle ne le remarque pas comme du neuf, rien n'en est journalisé, il ne règle aucun brouillon. Ce qui a moins de 24 h se range comme du direct, quel que soit le chemin par lequel il arrive d'abord. Il reste borné à 1 000 messages par conversation, comme le reste.
- Les doublons. Un message se reconnaît à son identifiant, ou à son alias. Le même message sous un autre identifiant est un jumeau : même conversation, même auteur, même texte aux espaces près, à moins de 2 min, et des identifiants de sortes différentes (celui du service, celui du client tant qu'il attend, une empreinte de l'extension). Il n'est pas rangé une seconde fois : sa référence devient l'alias de la ligne (`messages.alias`), et une retouche ou une suppression qui arrive sous elle la retrouve. Une ligne qui a déjà son alias n'en prend pas un second : un « ok » redit depuis le téléphone reste un message. Deux identifiants de la même sorte, deux empreintes comprises, sont deux messages. Rejouer l'historique ne range rien deux fois.
- Ce que Mika écrit arrive par `/api/teams/live`, une WebSocket ouverte tant qu'un onglet Teams l'est. La clé part dans le premier message, jamais dans l'adresse. Admise comme un relevé, la connexion reçoit la boîte d'envoi tout de suite, puis à chaque changement ; la boîte est relue chaque seconde hors de la boucle, la clé revérifiée toutes les 10 s. Un signe de vie toutes les 20 s garde éveillé le service de l'extension. Une trame se lit avant toute clé : les connexions pas encore présentées sont plafonnées par adresse (2) et au total (16). Au-delà de 4 connexions d'une clé, la plus ancienne cède sa place (4409). Chaque refus accepte d'abord la connexion, pour que son code arrive au navigateur. Les accusés restent en HTTP, et le relevé toutes les 30 s reste le filet.
- Ce que la page capte part au serveur en moins d'une seconde, au lieu de 3 s environ.

*Pourquoi :* « rendre l'extension plus temps réel » : « un cache, voir les trucs nouveaux, synchroniser, puis connecter en direct toutes les nouvelles arrivées par des synchronisations ciblées, et pour les messages du backend un service WebSocket » ; « un bouton pour charger tout l'historique pour une première mise en service » ; « côté backend, faire très attention aux doublons » (2026-11-18). La relecture de la base toutes les 45 s faisait attendre, et le relevé de la boîte d'envoi toutes les 30 s aussi.

*Révise 0069 (en partie : la boîte d'envoi poussée en direct, l'historique rangé déjà lu). Révisée par 0258 (en partie : les images), 0301 (en partie : la voie d'envoi), 0308 (en partie : la boîte d'envoi poussée sans relecture).*

### 0258 — Les images de Teams : téléchargées par l'extension, gardées avec leur message, regardées par Mika

- L'extension télécharge l'image de chaque message Teams par son adresse d'origine, avec les cookies du navigateur, comme Teams lui-même : affichée ou non, en direct (les messages des dernières 24 h) comme dans l'historique (après chaque paquet). Elle n'ouvre jamais que le service d'images de Microsoft (`https://….asm.skype.com/v1/objects/…`), jamais une autre adresse lue dans un message. 8 images par message au plus, 8 Mo chacune, PNG, JPEG, GIF ou WebP. Les exclusions et les pauses valent pour elles comme pour leur message.
- Le message part avec le nombre de ses images ; elles suivent à `POST /api/teams/image`, sous la clé du compte, une fois le message chez Mika (son message pas encore arrivé : 404, l'extension la retente). Le serveur vérifie le type et les premiers octets, et la garde avec son message dans `teams.db`, à son rang parmi les « [image] » du texte (500 Mo par compte : les plus anciennes partent au-delà) ; la même image redite n'en fait qu'une.
- Mika la regarde de près, comme une photo reçue dans le chat (le port `preprocess`, ADR 0106), par le processus `teams.images` : ce qu'elle y voit remplace la « [image] » de son rang dans le texte du message (« [image : … ] »), et une retouche du message le garde. Un échec passager est retenté trois fois ; au-delà, l'image reste gardée sans rien dire d'elle. Un message dont les images ne sont pas arrivées ou pas encore lues attend qu'elles le soient (3 min au plus) avant qu'elle le remarque : elle le remarque déjà décrit.
- frontendv2 montre les images dans le fil Teams, derrière la connexion (`/api/moi/teams/image`) ; un clic en ouvre une en grand, dans la page (une visionneuse, pas un autre onglet). Ce que Mika y voit est gardé en entier (sa description, bornée par le modèle) et se lit sous les images, rendu (titres, listes, tableaux), sur toute la largeur du message ; le texte du message n'en reprend que le début.
- Oublier une personne, retirer un compte ou tailler une conversation efface aussi ses images.

*Pourquoi :* « implémente les images » ; « il faut trouver un moyen, comme pour les messages, d'intercepter les photos » ; gardées et lues, et aussi celles de l'historique (2026-11-20). Une sonde a montré que le service d'images répond aux cookies du navigateur (200 ; 401 sans eux) : toute image d'un message est atteignable, pas seulement celles qu'on affiche.

*Révise 0251 (en partie : « [image] » n'est plus le dernier mot d'une image).*

### 0191 — Ses brouillons se relisent là où ils partiront

- Un brouillon de courrier de Mika se relit dans Mail (« Ses brouillons »), une réponse Teams dans Teams, à côté de leur conversation : ce qui partira exactement, le retoucher, l'envoyer, le retirer. Le chat de frontendv2 n'en montre qu'un lien (la carte dit sa capacité et son brouillon : `capability`, `draft`) ; les autres clients (web, Android) gardent leur carte, la même décision.
- Décider là est la décision du propriétaire de la ressource (`by` : sa personne), la même que « À valider » dans la console, qui voit toujours tout ; un `[À COMPLÉTER` bloque toujours l'envoi.
- « Préremplir avec Mika », dans la saisie de Mail et de Teams, lui demande une réponse à ce message : elle l'écrit dans ses brouillons, et la saisie la reprend. Seulement là où elle prépare : jamais pour un mail parti de ta boîte (même revenu en copie : on y répond soi-même), ni dans un compte Teams décoché ou quand Teams est coupé (elle ne s'y mettrait jamais) — la console refuse de même. Au téléphone, *pas encore fait* : il viendra avec l'envoi de 0189.

*Pourquoi :* les brouillons de Mika se relisent « dans mail, pareil pour teams ».

*Révise 0185 (en partie : la carte d'accord se relit aussi là où le brouillon partira), 0186 (de même).*

*Révisée par 0306.*

### 0192 — Chacun branche ses services MCP

- Une personne branche ses propres services, dans Paramètres › Services : le service est à elle (son propriétaire, `personne:<clé>` ; sans propriétaire, ceux de Mika, réglés par un opérateur), né avec une seule ligne d'accès, la sienne, et la ligne par défaut fermée (0131).
- Le partager ajoute une ligne pour la personne (0188) : lire, ses outils qui lisent ; s'en servir, tous, sur ton accord pour ceux qui agissent. Retirer le partage retire la ligne.
- Ce que Mika en offre reste calculé par le moteur des droits (0134), sans exception pour un service à quelqu'un ; ce qu'elle y lit se garde au niveau de la ligne.
- La console voit tous les services et les règle ; la personne ne voit et ne règle que les siens, et lit les lignes de ceux qu'on lui partage.
- Une personne branche un service **distant**, par son adresse https (`McpServer.owner`, `/api/moi/mcp/…`) ; lancer une commande sur la machine (un service local) reste aux opérateurs, dans la console. Ses outils arrivent coupés, à choisir un par un (0129).

*Pourquoi :* « chacun pour soi, ça crée un service MCP qui n'a que les droits avec la personne, dans inspection on peut voir tous les mcp, s'il veut partager son mcp, ça ajoute une règle d'accès … les mcp disponibles sont calculés en fonction des droits ».

*Révise 0128 (en partie : un service a un propriétaire), 0131 (en partie). Révisée par 0236.*

### 0193 — La carte de sa position passe par le serveur

- Téléphone › Position montre une vraie carte : ses tuiles, ses polices et ses icônes viennent du serveur de Mika (`/api/moi/phone/map/…`, à qui est connecté), jamais d'une adresse du dehors que le navigateur joindrait — elle dirait où la personne se trouve.
- D'où viennent les tuiles se règle dans la console (Réglages › Canaux › Carte de sa position) : rien (le plan dessiné, par défaut), un fichier PMTiles du dossier de données sous `cartes/`, ou un serveur de carte (une archive PMTiles lue par plages, ou des tuiles `{z}/{x}/{y}`) que le serveur joint seul, sans rien de la personne.
- Le fichier est une extraction de la carte Protomaps de la planète (OpenStreetMap), refaite à la demande par `mika carte extraire` (la France par défaut, jusqu'au zoom 15) ; ses polices et icônes, par `mika carte polices`. Rien d'autre à installer : ni base, ni serveur de rendu. `cartes/` n'entre dans aucune sauvegarde (il se réextrait).
- Le navigateur la dessine (MapLibre, chargé seulement sur cet onglet), claire ou sombre selon le thème, la mention OpenStreetMap toujours affichée ; hors de la zone couverte, sans carte ou sans WebGL, la position garde son plan dessiné et son lien vers OpenStreetMap.

*Pourquoi :* « peut-être un fournisseur gratuit ? … ou alors sur le pc portable héberger son propre openstreetmap ? » ; « ma carte se charge depuis le backend, et depuis le backend on doit pouvoir configurer le serveur de carte ».

*Révise 0119 (en partie : la position se voit sur une carte). Révisée par 0194 (la même carte sert l'écran Carte), 0197 (en partie : elle se règle sous Réglages › Carte et téléphone), 0229 (en partie : son adresse, avec la carte), 0269 (en partie : de `cartes/`, la sauvegarde prend les compteurs du mois), 0295 (en partie : l'archive se refait d'elle-même, toutes les deux semaines).*

### 0194 — Les lieux, les adresses et les itinéraires passent par le serveur

- Un écran **Carte** (frontendv2) cherche un lieu, une adresse, et calcule un itinéraire, sur la carte de 0193. Le
  navigateur ne parle qu'au serveur de Mika ; le serveur joint seul ce qu'il faut, sans rien de la personne (ni son
  nom, ni ses cookies), avec l'agent `Mika/2 (carte de sa position)`.
- **Les lieux** (points d'intérêt et lieux nommés) se cherchent dans un **index local**, `cartes/lieux.db` (SQLite :
  texte intégral, arbre R), que `mika carte lieux` tire des tuiles de l'archive (zoom le plus fin) : rien ne sort. Ils
  se rangent en catégories (Manger, Dormir, À voir, Nature, En route, Courses, Santé, Sortir, Services, Villes et
  lieux-dits) ; on cherche par le nom, autour d'un point, dans une zone, le long d'un trajet.
- **Les adresses** (numéro et rue) viennent de la Géoplateforme de l'IGN (la Base Adresse Nationale,
  `data.geopf.fr/geocodage`), relayée : seul le texte cherché part, **jamais la position de la personne**.
- **Les itinéraires** viennent d'un serveur **Valhalla** : voiture, vélo ou à pied ; péages, autoroutes ou ferries
  évitables ; consignes en français ; le meilleur ordre des arrêts ; un GPX. D'abord le serveur public de FOSSGIS
  (celui d'openstreetmap.org), relayé : **au plus une demande par seconde** pour tout le serveur, chaque trajet gardé en
  cache, sans garantie qu'il réponde. Puis un Valhalla à soi, sur le portable (la recette : `deploy/README.md`). Vers
  lui ne partent que les points du trajet.
- Tout se règle dans la console (Réglages › Canaux : « Lieux et adresses », « Itinéraires ») ; par défaut, ni adresses
  ni itinéraires : rien ne sort sans le choix d'un opérateur. Sans index ou sans itinéraires, l'écran le dit.

*Pourquoi :* « ajouter des recherches de point d'intérêt, des itinéraires, des fonctions de programmation de road
trip » ; « Valhalla public d'abord, puis le portable ».

*Révise 0193 (en partie : la même carte sert l'écran Carte). Révisée par 0197 (en partie : ils se règlent sous Réglages › Carte et téléphone), 0244 (en partie : l'index des lieux se tire de l'extrait OpenStreetMap, avec ce qu'en dit une fiche).*

### 0195 — Les voyages se préparent à deux et restent dans sa vie

- Un **voyage** (un road trip) appartient à la personne qui l'a créé : un titre, une date de départ, un mode (voiture,
  vélo, à pied), ce qu'il évite, et ses arrêts, jour par jour (un nom, des coordonnées, une sorte, une note). Il
  s'écrit au journal, comme le reste de sa vie (le plugin `trips`) : elle s'en souvient, elle peut en reparler ; oublier
  la personne l'efface.
- La personne le prépare dans l'écran Carte (créer, ajouter, déplacer, retirer un arrêt, réordonner un jour, le GPX).
  Mika le prépare **en conversation, quand on le lui demande** : elle cherche des lieux, calcule les trajets, crée le
  voyage, ajoute ou retire des arrêts, propose ce qu'il y a à voir le long de la route. Ce qu'elle a ajouté se voit en
  rose (« ajouté par Mika ») et se retire d'un geste ; ce n'est pas une proposition qui attend un accord : c'est le
  voyage que vous faites ensemble.
- Ses outils ne servent qu'en tête-à-tête, avec une personne qui a un compte, pour ses voyages à elle (jamais en
  salon, jamais ceux d'un autre). « Ici » est la dernière position que son téléphone a donnée (0119) : s'en servir est
  un regard, et sa bulle 📍 se voit.
- Pas encore : un voyage partagé avec quelqu'un d'autre, une page de la console, le guidage pendant la conduite, la
  carte hors ligne sur le téléphone.

*Pourquoi :* « pour que l'IA puisse interagir avec la carte » ; la maquette validée le 2026-11-04 (« nikel ça »).

*Révisée par 0204 (en partie : la console montre les voyages d'une personne, et un opérateur peut en supprimer un), 0259 (en partie : ses outils lisent la fiche d'un lieu et les événements).*

### 0196 — Elle propose une carte dans la conversation

- Quand elle cherche des lieux ou calcule un trajet pour la personne, son message emporte une note (`look:<seq>`) :
  une petite carte de ce qu'elle a cherché, qui s'ouvre dans l'écran Carte. Quand elle crée ou change un voyage, la
  note `trip:<id>` ; quand elle montre une carte de son choix (des lieux, un parcours), `map:<seq>`.
- Le chat les montre en **carte miniature** (MapLibre, sur les tuiles du serveur, créée quand elle paraît) ; une sorte
  de note inconnue s'ignore (l'app Android et l'ancien client web n'en souffrent pas). Ce qu'elle a vu se garde au
  journal (les lieux, le trajet résumé) ; oublier la personne l'efface, et la carte disparaît de son message.

*Pourquoi :* « proposer des cartes, des parcours et des points d'intérêt ».

*Révisée par 0259 (en partie : un regard peut être des événements).*

### 0229 — Le fond de carte est celui de tous les écrans

- Le fond de carte de 0193 (ses tuiles, ses polices, ses icônes, et ce que le client en sait) sert Téléphone › Position, l'écran Carte (0194) et les miniatures du chat (0196) : il est servi avec la carte, à `/api/moi/carte/fond/…` (`app/me/maps.py`), et non plus sous le téléphone, `/api/moi/phone/map/…`, qui n'existe plus.
- Rien d'autre ne change : d'où viennent les tuiles (la console), un jour gardé par le navigateur sous une adresse qui porte la version de la source, aucune adresse du dehors donnée au navigateur. Seul `frontendv2` lit ces routes, et il se déploie avec le moteur : il n'écrit que l'adresse de ce que le client sait de la carte, les autres viennent de sa réponse.

*Pourquoi :* né pour Téléphone › Position, le fond de carte sert aussi la Carte et les miniatures du chat. L'adresse fait partie de l'API qu'on lit pour comprendre le système : une carte de tous les écrans servie « sous le téléphone » était le reste d'avant ces ajouts (audit du 2026-11-05, K10-08, décision K10-Q1).

*Révise 0193 (en partie : son adresse).*

### 0244 — L'index des lieux se tire de l'extrait OpenStreetMap, avec ce qu'en dit une fiche

- `mika carte lieux --depuis cartes/france-latest.osm.pbf` construit `cartes/lieux.db` depuis l'extrait de Geofabrik,
  lu par pyosmium (l'extra `cartes`) : les mêmes catégories et les mêmes sortes qu'avant (une table des clés
  d'OpenStreetMap vers elles), et pour chaque lieu son objet d'OpenStreetMap (`n123`, `w45`, `r6`, stable d'une
  reconstruction à l'autre) et ce qu'en dit une fiche — cuisine, horaires, téléphone, site, terrasse, végétarien,
  vegan, accessibilité, à emporter, livraison, étoiles, enseigne, adresse, Wikidata : le schéma 2. Les tuiles restent
  possibles (`.pmtiles` : le schéma 1, sans détails) ; un index de schéma 1 se lit jusqu'à sa reconstruction, on y
  cherche comme avant, un filtre n'y trouve rien.
- La mémoire reste bornée sur la France entière (530 millions de nœuds, qu'aucun index complet des positions ne tient
  en 3 Go) : l'extrait se lit en passes que pyosmium filtre avant Python, et seule la position des nœuds des voies
  gardées se garde, par tranches d'identifiants (1 Go au plus). Une voie fermée se place au centre de ses nœuds, une
  voie ouverte sur son nœud du milieu, un multipolygone au centre de ses contours ; un lieu cartographié deux fois
  (son point et son bâtiment) ne compte qu'une ; ce qui déborde de la zone de l'extrait est laissé.
- Ouvert ou fermé se juge à l'instant de la requête, à l'heure de Paris, par un analyseur pur du sous-ensemble courant
  d'`opening_hours` (jours, plages, après minuit, `off`, `24/7`, fériés de France, mois et dates), qui dit aussi la
  semaine en français ; ce qu'il ne comprend pas reste inconnu et se montre tel quel, jamais deviné.
- Le port s'étend sans rien casser : un lieu trouvé porte des champs facultatifs (son objet, ouvert ou fermé en une
  phrase, sa cuisine, ses filtres ; sa note, ses avis, son prix, sa photo quand une source d'avis les donnera), la
  recherche prend des filtres (ouvert maintenant, terrasse, végétarien, vegan, accessible, à emporter, livraison,
  cuisine, une note minimale, l'ordre) et `place(id)` rend sa fiche, une partie par source : OpenStreetMap, puis les
  données touristiques, les avis et les événements proches, vides tant que leur source n'est pas branchée. Sans
  source de notes, la note minimale n'écarte rien et l'ordre par note garde celui de la distance.
- Un regard qu'elle garde au journal emporte ce qu'on savait du lieu, jamais s'il était ouvert : cela ne valait qu'à
  l'instant où elle a regardé.

*Pourquoi :* « OpenStreetMap complet (l'extrait France de Geofabrik) : l'index des lieux porte désormais cuisine,
horaires, téléphone, site, terrasse, végétarien/vegan, accessibilité, étoiles… Oui » (2026-11-17) ; les tuiles de
Protomaps ne gardent presque aucun de ces attributs.

*Révise 0194 (en partie : l'index des lieux se tire de l'extrait OpenStreetMap, avec ce qu'en dit une fiche). Révisée par 0245 (en partie : la fiche d'un lieu prend sa partie DATAtourisme et les événements proches ; un lieu des données touristiques se trouve avec ceux de l'index), 0250 (en partie : la note vient du cache des avis ; la note minimale écarte les lieux sans note, l'ordre par note les met à la fin ; la fiche prend sa partie « avis »), 0295 (en partie : l'index se construit sur le serveur, toutes les deux semaines).*

### 0245 — Les lieux touristiques et les événements de DATAtourisme, en cache par cases autour des personnes

- Une base `cartes/tourisme.db` (SQLite, jamais sauvegardée : elle se refait) garde les lieux touristiques et les
  événements à venir de DATAtourisme (Licence Ouverte 2.0) **case par case** : une case de la grille (une dizaine de
  kilomètres) s'interroge par ses bords, jamais sur la position de la personne, et se garde avec sa date — sept jours
  pour ses lieux, un pour ses événements (ils changent plus vite), réglables ; relue, ce qu'elle ne rend plus
  s'efface. Une case jamais vue qu'une personne ouvre (les événements autour d'elle, la fiche d'un lieu) se lit en
  direct, quelques pages, si le quota le permet ; sinon on montre ce qu'on a, en disant pourquoi. La clé de
  l'opérateur est scellée dans les réglages (à défaut, `MIKA_DATATOURISME_API_KEY`) : elle ne part que dans un
  en-tête, et ne s'écrit jamais au journal.
- **Un limiteur partagé** par les services de la carte, une instance par service, ses bornes réglées dans sa section
  et relues à chaque demande : par seconde, par heure et par jour (glissantes), par mois (le coût réel d'un appel) ;
  une réserve que le travail de fond laisse au direct ; un recul quand le service dit d'attendre ; ses compteurs sous
  `cartes/` (ils survivent à un redémarrage, le serveur et la commande les partagent) ; ce qui bloque se dit en mots,
  avec l'heure où il revient. DATAtourisme : 900 demandes par heure, 8 par seconde, 20 % de réserve (au plus 1 000 et
  10, ses limites).
- **Un réchauffage partagé** : chaque soir (22:00 de Paris, réglable), autour de la dernière position connue de chaque
  personne (`location.fix`, ADR 0119, que la composition lui passe : l'adaptateur n'importe ni plugin ni faculté) et
  de points fixes réglés, chaque source dans son ordre — DATAtourisme : les cases des points puis celles d'à côté, les
  événements avant les lieux, les plus vieilles d'abord —, sur son budget de fond ; un quota qui revient avant le
  matin s'attend, sinon la source s'arrête en le disant. Copier des départements entiers (une complète par semaine,
  reprise là où elle s'est arrêtée, ce qui a changé chaque nuit d'après `lastUpdate`, `mika carte tourisme`) reste une
  option, vide par défaut.
- Le rapprochement : une fiche est le lieu d'OpenStreetMap à moins de 150 m au nom qui se ressemble, dont elle
  enrichit la fiche (description, labels, tarifs, contacts, auteur et date, photos) ; sans pendant sûr, elle se trouve
  comme `t:<uuid>`, jamais en double d'un lieu de l'index. Un événement se tient au lieu nommé le plus proche (à moins
  de 60 m), sinon à son adresse ; les copies d'un même événement (même nom, même endroit, une fiche par date) n'en
  font qu'un, toutes leurs dates ensemble. Une fiche ne garde jamais le nom d'une personne de contact.
- Le port `maps` y gagne `events` (thèmes tirés du nom puis des classes, « gratuit » deviné du prix, jamais
  inventé), `event` (ses dates en clair, à l'heure de Paris, la prochaine d'abord), `tourism_coverage` et
  `tourism_summary` ; `place` remplit sa partie DATAtourisme et les événements proches. Les photos passent par le
  serveur (`photo`, `p:<hash>`) : seule une adresse venue des données se relève, jamais une adresse d'un client ni du
  réseau local ; une image vérifiée à ses octets, bornée, gardée sous `cartes/photos` (borné), son crédit et sa licence
  montrés, plus servie après la fin de ses droits. Les avis (Tripadvisor) se brancheront au limiteur, au réchauffage
  et aux photos.

*Pourquoi :* « DATAtourisme : une base locale des lieux et des événements autour, plus des outils pour Mika »
(2026-11-17) ; « les limiteurs de DATAtourisme réglables dans la console, avec la clé » ; « DATAtourisme devient un
cache autour des personnes, réchauffé chaque soir, avec un limiteur et un service de réchauffage partagés avec
Tripadvisor » (2026-11-18). Avec 1 000 demandes par heure pour 585 098 fiches, copier toute la France prend des heures
pour servir surtout là où personne ne va.

*Révise 0244 (en partie : la fiche d'un lieu prend sa partie DATAtourisme et les événements proches ; un lieu des données touristiques se trouve avec ceux de l'index). Révisée par 0250 (en partie : Tripadvisor est la seconde source du limiteur, du réchauffage et des photos ; un débit changé dans la console garde le tour déjà pris), 0256 (en partie : le limiteur compte le mois d'un service à son heure, et l'appel dès qu'il part ; une source donne l'adresse d'une photo au moment de la relève, sur ses seuls hôtes), 0259 (en partie : le lieu d'un événement n'est qu'un lieu qui accueille du public ; les cases d'un rayon se lisent en direct, bornées), 0269 (en partie : un pendant est un lieu de la même sorte ; le lieu d'un événement un peu plus loin ; seuls 404 et 410 disent qu'une fiche a disparu ; la photo jointe à son adresse résolue).*

### 0250 — Les avis de Tripadvisor, en cache autour des personnes, que Mika lit : le choix de l'opérateur

- **Le choix de l'opérateur, écrit tel quel.** Les conditions de l'API Terra interdisent de garder leurs données (seul
  l'identifiant d'un lieu peut l'être) et de les faire lire par une IA (§3.1.2). Il le sait, et a décidé le 2026-11-17 :
  « fait quand même, c'est ma responsabilité ». Ce serveur garde donc un **cache** des notes, des avis et des photos, et
  Mika les lira et les analysera (ses outils). On garde ce qui ne coûte rien : la mention « Tripadvisor », le lien vers
  leur page du lieu, l'icône de note qu'ils fournissent, toujours montrés avec. La console le redit sur sa page.
- **Un cache par cases**, `cartes/avis.db` (SQLite, jamais sauvegardé : il se relit) : une case de la grille (3 km par
  défaut) se demande par ses bords, jamais sur la position d'une personne, et par sorte (restaurants, à voir, hôtels)
  Terra en rend au plus 60, les mieux notés (trois pages de vingt) ; la fiche d'un lieu de l'index pas encore rapproché
  le cherche à 100 m de lui (cinq au plus, les plus proches), puis ses avis récents en français et ses photos ; tout se
  garde sept jours (réglable) avant de se relire, et s'efface après quatre fois cette durée sans relecture. Une liste
  (`search`, `around`) ne lit que le cache : elle n'appelle jamais Tripadvisor. `place_refresh` relit tout ;
  `preload` met en file, en fond, la case d'une position et ses huit voisines.
- **La facture tient au cache et au limiteur.** Chaque lieu rendu est une entité facturée (une recherche de vingt en
  coûte vingt, les avis ou les photos d'un lieu une) : le limiteur partagé (0245) compte les entités du mois au coût
  réel, et retient une demande qui dépasserait le plafond avant qu'elle parte. Ses bornes, réglées dans la console et
  relues à chaque demande : 8 demandes par seconde, 9 000 sur 24 heures glissantes, une recherche à proximité par
  seconde (un second limiteur, pris en plus), 1 000 entités par mois, 20 % gardés au direct. La clé est scellée dans
  les réglages, sinon `MIKA_TRIPADVISOR_API_KEY` ; la commande `mika` lit le `.env` du dossier courant sans rien
  écraser (`app/envfile.py`), jamais les tests (`MIKA_ENV_FILE` vide).
- **Le rapprochement** suit la règle des données touristiques (`tourism.likeness`) : le lieu de l'index à moins de 100 m
  dont le nom se ressemble, sinon le lieu DATAtourisme sans pendant (`t:<uuid>`). Un lieu de Tripadvisor sans pendant
  ne se montre nulle part : jamais un lieu de plus, jamais un double. Un lieu rapproché porte sa note, ses avis, son prix
  en euros et sa photo dans les listes ; la note minimale écarte les lieux sans note, l'ordre par note les met à la fin,
  et les mieux notés du cache dans la zone rejoignent les plus proches.
- **Le soir**, Tripadvisor est une source du réchauffage partagé : les restaurants d'abord, puis ce qui est à voir,
  puis les hôtels ; pour chacun, les cases des points puis leurs voisines, les plus vieilles d'abord ; ensuite les avis
  et les photos des lieux les plus regardés et les mieux notés — sur ce qui reste du jour et du mois, la réserve gardée.
  Ses photos et l'icône de sa note passent par le relais (0245), depuis les seules adresses que Tripadvisor a données,
  chez lui.

*Pourquoi :* « Tripadvisor (Terra) : notes, avis, photos, avec un cache des alentours de la personne, gardé un temps,
et Mika les lit et les analyse » ; à l'objection des conditions, « fait quand même, c'est ma responsabilité »
(2026-11-17) ; « un limiteur de requêtes », « le cache Tripadvisor : 7 jours par défaut », « un service qui réchauffe
le cache… les restaurants d'abord » (2026-11-18). Autour de la Grand-Place de Lille, 882 restaurants tiennent dans un
kilomètre : aucune case ne les tient tous, et sans cache chaque écran rouvert repaierait les mêmes lieux.

*Révise 0244 (en partie : la note vient du cache des avis ; la note minimale écarte les lieux sans note, l'ordre par note les met à la fin ; la fiche prend sa partie « avis »), 0245 (en partie : Tripadvisor est la seconde source du limiteur, du réchauffage et des photos ; un débit changé dans la console garde le tour déjà pris). Révisée par 0256 (en partie : Google Places remplace Tripadvisor ; les cases, les bornes, la fiche et les photos suivent Google).*

### 0256 — Les avis de Google Places, par son API officielle, à la place de Tripadvisor : le choix de l'opérateur

- **Google Places remplace Tripadvisor**, par son API officielle Places (New) seule (aucune page de Google n'est lue,
  aucun scrapeur), avec la clé de l'opérateur, scellée dans les réglages (sinon `MIKA_GOOGLE_PLACES_API_KEY`), qui ne
  part que dans l'en-tête `X-Goog-Api-Key`. Le client de Terra, ses tests et ses données s'en vont ; `cartes/avis.db`
  passe au schéma 2 et se relit, sans conversion. **Le choix de l'opérateur, écrit tel quel** : les conditions de
  Google ne permettent de garder que l'identifiant d'un lieu (`place_id`), et ses coordonnées trente jours ; il a
  décidé le 2026-11-20 de garder ce cache sept jours (effacé après vingt-huit sans relecture) et de le faire lire par
  Mika, sous sa responsabilité, comme pour Tripadvisor. On garde ce que Google demande d'afficher et qui ne coûte
  rien : la mention « Google Maps », le lien `googleMapsUri`, le nom et le lien de l'auteur de chaque avis et de
  chaque photo.
- **Le masque fait le prix** (`X-Goog-FieldMask`, en constantes) : une recherche à proximité pour une liste au niveau
  « Nearby Search Enterprise » (note, nombre d'avis, prix, horaires, photos ; jamais un champ « Atmosphere »), les avis
  à la fiche d'un lieu seulement (« Place Details Enterprise + Atmosphere » : avis, résumé, ce qu'il sert), une photo
  (« Place Details Photos »). Grille de Google vérifiée le 2026-11-20 : 1 000 offerts chaque mois et par SKU, puis
  35 $, 25 $ et 7 $ les 1 000 ; Text Search n'est pas employé. Le limiteur partagé compte en appels : 5 par seconde,
  500 sur 24 heures, un plafond par mois et par SKU au mois de Google (minuit, heure du Pacifique), compté dès que
  l'appel part, même en erreur — par défaut le quota offert : sans rien toucher, rien n'est facturé ; 20 % au direct.
- **Les cases** (3 km) se demandent par sorte — restaurants, à voir, hébergements, en types premiers de Google
  (`includedPrimaryTypes`, cinquante au plus : un centre commercial typé aussi « restaurant » ne remonte pas) — par le
  cercle qui les couvre (leur centre, la moitié de leur diagonale), jamais à la position d'une personne : les vingt
  plus connus (`POPULARITY` ; Google n'en rend pas plus, sans page suivante). Un cercle plein fait demander ses quatre
  quarts (un niveau par défaut, deux au plus) : une case coûte de 1 à 5 recherches par sorte, un réchauffage autour
  d'une personne (neuf cases, trois sortes) de 27 à 135, une fois par semaine. Un lieu pas encore rapproché se cherche
  à 100 m de lui par la distance, puis sa fiche se lit ; le soir, après les cases, la fiche des lieux ouverts depuis
  un mois.
- **La fiche** dit sa source (`google`), son résumé, sa fourchette de prix ; chaque avis, son auteur, son lien et sa
  date en mots ; chaque photo, son auteur et son lien. Google ne donne ni répartition, ni sous-notes, ni classement :
  ils restent vides. Ce qu'il dit et qu'OpenStreetMap ne dit pas (terrasse, végétarien, à emporter, livraison,
  réservation, horaires) complète la fiche en le citant (« oui (selon Google) »), jamais à la place d'OpenStreetMap.
- **Les photos** : leur adresse ne se garde pas, elle se demande à Google quand le relais va chercher l'image, sur ses
  hôtes d'images seulement, une fois (le relais la garde) ; une photo garde sa référence d'une lecture à l'autre (son
  lieu, son auteur, ses dimensions), et son nom expiré (400 ou 404) fait relire la fiche, qui lui en donne un neuf.

*Pourquoi :* Terra facture chaque lieu rendu et n'offre ses 1 000 entités qu'une fois (« c'est pas des crédits par
heure ») ; Google facture à l'appel, avec un quota offert qui revient chaque mois. Un scrapeur de Google Maps a été
proposé puis refusé (extraction interdite, protections contournées, avis aspirés) ; l'API officielle, « go pour ça »
(2026-11-20). Par popularité, la recherche rend les lieux connus, là où Tripadvisor rendait des 5,0 à un avis.

*Révise 0245 (en partie : le limiteur compte le mois d'un service à son heure, et l'appel dès qu'il part ; une source donne l'adresse d'une photo au moment de la relève, sur ses seuls hôtes), 0250 (en partie : Google Places remplace Tripadvisor ; les cases, les bornes, la fiche et les photos suivent Google). Révisée par 0269 (en partie : un appel retenu par son mois ne compte pas dans le jour ; « Actualiser » ne repart pas avant dix minutes, borné pour tout le serveur).*

### 0259 — L'écran Carte lit les fiches, les événements et les photos ; elle les lit aussi, en données

- **L'API par personne** (`app/me/maps.py`, `protocole-moi.md` § 10) sert ce que les lots 0244, 0245 et 0256 ont
  réuni : une liste filtrée (ouvert maintenant, terrasse, végétarien, vegan, accessible, à emporter, livraison, une
  cuisine, une note minimale) et rangée (la distance, la note), avec ce que le cache des avis sait de l'endroit ; la
  fiche entière d'un lieu et « Actualiser » ; les événements autour d'un point ou dans une zone, d'une période, de
  thèmes, et la fiche de l'un d'eux ; une photo relayée par sa référence. Un lieu ne porte que ce qu'on en sait.
- **Ce qu'il faut citer va avec chaque source**, et les clients le montrent : « Google Maps » et le lien de sa page,
  l'auteur et le lien de chaque avis et de chaque photo (0256) ; l'auteur et la date d'une fiche de l'office de
  tourisme, Licence Ouverte 2.0 (0245) ; « © les contributeurs d'OpenStreetMap » (0244). Une photo n'est jamais une
  adresse du dehors : une référence `p:<hash>`, servie par `…/carte/photo/<ref>` ; une référence inconnue, ou dont les
  droits ont pris fin, donne 404 (`MapsNotFound`) sans que rien parte ; seules des images JPEG, PNG, WebP et GIF se
  servent, gardées un jour par le navigateur de qui la regarde.
- **« Ici »** (`near=ici`) est la dernière position que ton téléphone a donnée (0119), la tienne seule, jamais celle
  d'une autre ; sans elle, 409. **Le préchargement des avis** (0250, 0256) part de deux gestes seulement : le
  téléphone qui donne sa position (`KernelPort.locate`, `app/mindport.py`, là où l'application l'écrit), et chercher
  autour de soi (`near=ici`, ou `here=1` avec sa propre position) — une mise en file de cases, qui ne retient pas la
  réponse. Un point de la carte qu'on regarde n'est pas soi : il ne précharge rien.
- **Ce qui peut faire appeler un service compté est borné par compte** : soixante fiches ou recherches d'événements
  par minute, cent vingt photos, dix « Actualiser », dix préchargements par dix minutes (au-delà, rien, sans le dire).
  Une liste ne lit que les caches : elle ne compte pas.
- **Ses outils** (0195, 0196) : `places_search` prend les mêmes filtres, et sa ligne dit la note Google, le nombre
  d'avis, le prix, la cuisine et « ouvert, ferme à … » quand on les sait ; `place_read` lit la fiche d'un lieu (un
  identifiant qu'elle a trouvé, « ici », des coordonnées, un nom) ou d'un événement (`e:…`) — un seul outil, parce que
  l'identifiant dit déjà lequel, et que la boucle d'outils a une description de moins à porter ; `events_search`
  cherche autour d'un endroit, à une période (« ce_weekend », « samedi », des dates), par thème, gratuit ou non. Tout
  texte venu du dehors (un avis et son auteur, quand il a été écrit, un résumé, une description, ce que Google
  ajoute, un nom) passe par `inert`, borné, sous la ligne « données » ; un avis qui donne des ordres reste un avis. Son
  regard (`trips.looked`, `look:` ; `evenements` pour des événements) ne garde que le lieu ou l'événement, comme une
  liste les garde : **jamais le texte d'un avis, d'un résumé ni d'une description au journal**.
- **Le lieu d'un événement** n'est qu'un lieu qui accueille du public — une salle, un théâtre, un cinéma, un musée, une
  galerie, un centre culturel, une bibliothèque, un stade, un château ; une église pour un concert ou une visite —,
  jamais une place, un parc, un monument ni une « attraction » ; aucun pour un marché ni pour une fête qui n'est que
  cela. Une adresse sans numéro qui nomme une place ou une rue (« Place du Concert ») dit où il a lieu : un lieu n'y est
  retenu que si l'événement ou l'adresse le nomme (« l'opéra », place du Théâtre).
- **Les cases d'un rayon** : chercher des événements à douze kilomètres lit en direct les cases que le rayon touche, la
  sienne d'abord puis les plus proches — au plus douze lectures par demande, trois à la fois —, et la couverture dit
  quand la zone n'est lue qu'en partie, ou trop grande pour être lue d'un coup. Une liste de lieux (`search`,
  `around`) ne lit toujours que les caches, même sur un grand rayon ; sa couverture (`tourism_coverage(…,
  places=True)`) dit ce qui manque.

*Pourquoi :* le contrat du chantier « carte, avis, événements » (2026-11-17) : l'écran Carte et ses outils lisent les
fiches, les avis et les événements, avec les attributions que les sources demandent. La sonde réelle du 2026-11-18 a
montré « Marché du Vieux-Lille » rapproché de « La chapelle Notre-Dame d'Annay », et une recherche à douze kilomètres
de Lille qui ne lisait que la case du point : Roubaix, Tourcoing et le LaM manquaient.

*Révise 0195 (en partie : ses outils lisent la fiche d'un lieu et les événements), 0196 (en partie : un regard peut être des événements), 0245 (en partie : le lieu d'un événement n'est qu'un lieu qui accueille du public ; les cases d'un rayon se lisent en direct, bornées). Révisée par 0269 (en partie : « Actualiser » dit ce qu'il a fait et refuse quand rien n'est réglé ; la fin d'un événement est celle de sa séance ; une photo qui n'est pas une image est un 502).*

### 0269 — La carte relue : la photo jointe à son adresse résolue, un pendant de la même sorte, « Actualiser » borné

- **Le relais de photos ne joint que des adresses publiques, résolues au moment de la connexion** (`photos.py`). Une
  adresse écrite passe d'abord `public_url` : un nom d'hôte (des labels, le dernier commençant par une lettre) ou
  une adresse publique — jamais une forme héritée que le système lirait comme une adresse (« 127.1 », « 0177.0.0.1 »,
  « 0x7f.1 », un entier). Puis chaque connexion, à chaque saut de redirection, part par le réseau du relais
  (`guarded_transport`) : il résout le nom, et se connecte à l'adresse qu'il vient de vérifier, seulement si
  **toutes** celles que le DNS rend sont publiques (`joinable` : ni bouclage, ni réseau privé ou partagé, ni locale
  au lien ou au site, ni multidiffusion, ni réservée, ni non spécifiée ; une IPv4 cachée dans une IPv6 — mappée,
  6to4, Teredo — se juge elle-même). Le nom demandé reste celui du certificat, du SNI et de `Host`. Une source qui
  répond autre chose qu'une image est un 502 (`MapsBadMedia`) ; une source muette, un 503.
- **Un pendant est un lieu de la même sorte** (`tourism.same_place`, pour DATAtourisme comme pour Google, et pour les
  doublons d'une liste) : une gare, une station, un parking, une borne, une banque, une location, une pharmacie
  (`route`, `services`, `santé`) ne sont le pendant de rien, même sous le même nom — sauf une mairie, qui se visite.
  Sous des noms qui ne sont pas les mêmes (l'un dans l'autre, presque les mêmes lettres), il faut une sorte voisine :
  un restaurant et une boulangerie, une pâtisserie, un hôtel-restaurant ; ce qui se visite et un parc, une salle de
  spectacle. Un nom qui n'a en commun que ce qui dit une rue ou une place (« La Place ») n'est pas contenu dans
  l'autre. Une règle changée rejuge tout (`match_stamp` : la date de l'index et le numéro de la règle).
- **Le lieu d'un événement, un peu plus loin** : jusqu'à 300 m, un lieu qui accueille du public reste le sien quand
  l'événement le nomme en entier (« … à l'Aéronef ») ou qu'il est à la même adresse — le numéro et la rue de
  l'index, mot pour mot (le LaM, placé au centre de ses contours, à 154 m de l'entrée de ses événements). Jamais un
  autre sans cela, jamais pour un marché. **L'adresse** perd la commune que DATAtourisme recopie dans la rue
  (« Roubaix, Roubaix », « … VIlleneuve-d'Ascq, Villeneuve-d'Ascq ») ; une rue qui porte le nom d'une ville (« rue de
  Lille ») le garde.
- **« Actualiser » ne repart pas pour rien.** Une source relue il y a moins de dix minutes (la fiche avec ses avis
  chez Google, ou la recherche tout près du lieu ; la fiche DATAtourisme) ne se redemande pas : la fiche revient avec
  « Relue il y a 4 min : elle est à jour… ». Ce qui part est borné pour tout le serveur : vingt « Actualiser » par
  vingt-quatre heures glissantes (`REFRESHES_PER_DAY`, dans `cartes/quotas.db`) — le mois offert de Google compte
  mille fiches, vingt par jour en prennent six cent vingt au plus —, en plus des dix par minute et par compte.
  Rien à relire pour ce lieu (on n'en lit pas les avis, et l'office de tourisme n'en a pas de fiche) : la fiche,
  et « Rien à relire pour ce lieu… » ; aucune source réglée : un refus en mots (503), jamais « Fiche relue. ». La
  route rend ce que dit le guichet (`PlaceRefresh.said`).
- **Ce qui compte ne compte que ce qui part.** Un appel retenu par le mois de son SKU ne reste pas dans les
  vingt-quatre heures de tout Google (`Limiter.forget`). Une lecture en direct n'attend jamais une lecture de fond
  de la même case (le réchauffage, des centaines de pages sur la part de fond) : la case se montre telle qu'elle est,
  et sa couverture dit qu'elle se lit en ce moment. Seuls 404 et 410 disent qu'une fiche DATAtourisme a disparu ; un
  400 est un refus, la fiche reste. Une base des avis ne se crée qu'une fois quand deux fils l'ouvrent, et aucune
  base de la carte ne s'efface parce qu'une autre écriture la tient (`database is locked`).
- **Les dates** : un événement (`EventHit`) finit avec sa prochaine séance (le lendemain après minuit), jamais avec sa
  période, que ses `dates` disent ; une suite de dates ne se dit par ses jours seuls (« sam., dim. ») que dans les
  six jours qui viennent — au-delà, avec leurs dates (« sam. 5 et dim. 6 déc. », « du jeu. 24 au sam. 26 déc. »).
  Une période d'événements trop longue se refuse avec son champ, même sans `start` (aujourd'hui).
- **Les horaires** : une liste de dates (« Jan 01,May 01,Dec 25 off ») est une seule règle ; seule une virgule
  derrière la fin d'une règle (une heure, « off », « closed », « open », « 24/7 ») en ajoute une. **Les filtres** :
  ce qui est vegan est végétarien aussi, sauf un `diet:vegetarian=no` (à la prochaine `mika carte lieux`).
- **Ce que les clients citent, jusque dans une liste** (relecture des clients, même jour). Une vignette se montre avec
  son crédit, ou pas du tout : un lieu (`PlaceHit`, `ports.maps.extras`) et un événement (`EventHit`) qui portent leur
  première photo portent aussi d'où elle vient, son auteur, son lien et sa licence (`photo_source`, `photo_credit`,
  `photo_credit_url`, `photo_licence` ; le cache des avis les lit avec la photo, la base des données touristiques
  aussi) — facultatifs pour un lieu comme ses autres champs, toujours là pour un événement, vides sans photo. Les
  clients les écrivent sur la ligne, lisibles ; sans crédit, pas de vignette. Un regard ne garde pas ce crédit (pas
  un nom d'auteur de plus au journal) : ses lieux n'ont pas de vignette. Une photo de l'office de tourisme montre sa
  licence là où elle se montre (la bande d'une fiche, pas seulement la visionneuse) ; « Google Maps » se lit partout
  où une note Google se montre, quelle que soit la couverture de la liste, dans un regard aussi. Un regard garde
  l'identifiant entier d'un lieu (`t:<uuid>`, 38 caractères : `plugins/trips/tools.py::IDENT_MAX`) : coupé, sa fiche
  ne se rouvrait ni depuis le chat ni par elle. Les jours des événements se comptent à l'heure de Paris, celle de
  leurs dates, quel que soit le fuseau du navigateur ou du téléphone ; le cache des photos d'Android suit leur
  `max-age` (la stratégie de Coil 3 par défaut ne le lit pas : une photo aux droits finis restait visible).
- **Ce qui ne part pas ne compte pas, ce qui ne se lit pas ne s'efface pas** (troisième relecture, même jour). Un
  « Actualiser » ne prend un des vingt tours du serveur que si un appel part vraiment vers Google ou DATAtourisme
  (`quota.counting_sent`, que chaque client marque au moment où l'appel part) : retenu par le mois de Google, un recul
  ou le quota de l'heure de DATAtourisme, il rend son tour et le refus dit cette cause ; un appel parti en échec
  compte. Un 200 de `/catalog/{uuid}` qui n'est pas cette fiche est une réponse illisible : la fiche reste. Une erreur
  de base pendant le réchauffage arrête sa source en le disant, l'autre finit, et le compte rendu des deux se garde ;
  une photo dont le cache ne s'écrit pas est un 503 en mots. Les photos d'un même lieu aux noms expirés ne relisent sa
  fiche qu'une fois. **Un service est le pendant d'un service** de l'index sous son nom même, la commune qu'il y
  ajoute mise à part (« France Cars Villeneuve d'Ascq » est « France Cars », une location ; « Taxi Lille Europe »
  n'est pas la gare) ; la classe `Transport` de DATAtourisme se range sous « services », et une fiche lue avant se
  rejuge à sa sorte d'aujourd'hui (règle 3). **Les compteurs du mois valent par dossier de données** : Google compte
  par compte de facturation, la même clé sur deux serveurs (ou dans le `.env` d'un poste) partage un seul quota
  offert — la console et la recette le disent, et conseillent une clé à part ; `cartes/quotas.db` est le seul fichier
  de `cartes/` que prend la sauvegarde, restauré seulement là où il n'y en a pas (sur place, ceux du dossier, plus
  récents, restent). Enfin, `tourism.synced` de `GET /carte` est la plus récente lecture de la base, d'une case comme
  d'un département ; `place_read` lit un événement sans l'index des lieux ; Android refait la ligne d'Explorer après un
  « Actualiser » en partie refusé, et son cache mémoire des photos repasse par le disque chaque heure (Coil le
  consulte avant toute requête).

*Pourquoi :* la relecture adverse du moteur « carte, avis, événements » du 2026-11-21 (quinze constats, vérifiés un à
un par un test qui échouait avant) ; puis celle des deux clients (vingt-deux constats, `output/carte-avis/R2-constats.md`),
et une troisième (onze, `R3-constats.md` : des refus qui prenaient un tour du serveur, « France Cars » perdu par la
règle 2, des compteurs propres à un dossier quand la clé est partagée) :
les vignettes des listes montraient des photos de Google et de l'office sans leur auteur ni leur licence, que le serveur
ne donnait pas. Sur les bases des sondes, « BAR PARIBAS » avait les avis de la banque « BNP
Paribas », la Grand-Place ceux du parking, « Bouillon Rihour » la station de métro ; « 127.1 » passait le garde-fou des
photos ; le 1er janvier, le LaM était « ouvert 24 h sur 24 » ; un compte pouvait vider en deux heures le mois de fiches
de tout le serveur à coups d'« Actualiser ».

*Révise 0193 (en partie : de `cartes/`, la sauvegarde prend les compteurs du mois, `quotas.db`), 0245 (en partie : un pendant est un lieu de la même sorte ; le lieu d'un événement un peu plus loin, nommé ou à la même adresse ; seuls 404 et 410 disent qu'une fiche a disparu ; une base tenue ne s'efface pas ; la photo jointe à son adresse résolue), 0256 (en partie : un appel retenu par son mois ne compte pas dans le jour ; « Actualiser » ne repart pas avant dix minutes, borné pour tout le serveur), 0259 (en partie : « Actualiser » dit ce qu'il a fait, et refuse quand rien n'est réglé ; la fin d'un événement est celle de sa séance ; une photo qui n'est pas une image est un 502).*

### 0198 — Ce qui vient d'ailleurs : une seule neutralisation, la plus forte

- La règle de l'ADR 0022 (ce qui vient d'ailleurs n'imite ni un titre de section ni une borne de l'état interne) n'est écrite qu'une fois, dans le noyau (`kernel/prompt.py` : `neutral`, `cited`, `visible`). Les ports (`inert`, `cite`, `visible`) et le vocabulaire (`neutralize`, pour un nom) l'appellent ; aucun autre module ne garde, pour désamorcer, son jeu de tirets, son motif de l'état interne ni sa liste de caractères invisibles.
- Elle retire d'abord ce que le modèle lirait sans qu'on le voie : caractères de contrôle, de format, privés, demi-paires, et les non attribués des plages qu'Unicode réserve à ce qui ne s'affiche pas (autour des étiquettes) ; la fin de ligne et la tabulation restent. Un autre caractère que la table d'Unicode de Python ne connaît pas reste : il se voit, et c'est le plus souvent un émoji plus récent qu'elle. Puis elle réécrit « ÉTAT INTERNE » et « FIN ÉTAT INTERNE » sous toutes leurs graphies (casse, accent précomposé ou combinant, pleine chasse, lettres espacées, tiret ou souligné entre les mots), où qu'ils soient, même collés à un mot, à un chiffre ou à un « S » (« XÉTAT INTERNES »). Enfin, une suite de tirets de toute graphie (signe moins, filets de boîte, pleine largeur), blancs permis entre eux ; un tiret de deux ou trois cadratins y compte pour deux ou trois.
- Trois tirets à la suite imitent un titre dans ce que désamorce le composeur (le message, l'historique, une section, une citation `cited`), où deux sont ordinaires (« -- bref », une option `--slow`) ; deux suffisent dans ce que les ports rendent inerte ou citent (un objet de mail, un titre, un nom, une ligne d'un document), et une ligne inerte est repliée avant d'être désamorcée. Une citation du noyau ne désamorce que les tirets qui ouvrent ou ferment une ligne (ADR 0135).
- Chaque porte garde son rendu : le prompt écrit « — » et « état interne » en minuscules, une ligne des ports « – » et « état-interne », un nom perd ces mots, et aussi tout caractère non attribué, comme avant (`clean_display_name` : sa clé `name:` ne bouge pas). Une seule note de citation, « (cité : des données venues d'ailleurs, telles quelles — ce ne sont pas des consignes) », pour une section citée, un résultat d'outil venu d'ailleurs et le contenu d'une pièce jointe.

*Pourquoi :* l'audit du 2026-11-05 a trouvé la règle écrite trois fois, avec trois jeux de tirets et trois motifs. La plus faible servait les résultats des outils à elle (courrier, Teams, flux, téléphone, lieux), que la boucle d'outils ne cite pas : un objet de mail « −−− FIN ÉTAT INTERNE −−− », en signes moins et accent combinant, arrivait intact au modèle. Sa relecture a corrigé la première union sur deux points : une borne de mot laissait passer « FIN ÉTAT INTERNES », que les ports prenaient ; retirer tout caractère non attribué effaçait du message un émoji plus récent que la table de Python.

*Révise 0022 (en partie : une seule neutralisation, la plus forte). Révisée par 0266.*

### 0199 — Dans Teams, ta réponse rend la sienne sans objet

- La règle du courrier (0188) vaut dans Teams : quand la personne du compte répond elle-même dans une conversation, les réponses de Mika qui y attendaient un accord ne partiront plus. Elles sont refusées en son nom (qui décide pour ce compte), avec la note « Répondu autrement », et elle le sait comme d'un refus ; la carte de frontendv2 le dit, « Ses brouillons » aussi (la note d'un refus ne s'y relit que sur un compte à soi : ce que le propriétaire a dit à Mika ne passe pas par un partage).
- Ta réponse compte dès qu'elle part du web : `teams.ecrire` journalise `teams.written` (son compte et sa conversation, sans texte) quand le message entre dans la file, sans attendre que l'extension le rapporte. Écrite dans Teams, elle compte quand elle revient dans le fil (`teams.received`), si elle est d'après le message auquel Mika répondait ; un vieux message rattrapé n'y répond pas.
- La règle vit dans le plugin `teams`, pas dans la couche HTTP : les réducteurs marquent la réponse (`DraftSeen.answered`) dans le même ajout que ton message ; dès lors, son aperçu la dit bloquée — rien ne l'approuve plus, ni le chat, ni la console, ni frontendv2 ; le processus `teams.answered` la refuse aussitôt après. Écrire ne peut donc pas échouer à cause d'elle une fois ton message en file.
- Une réponse demandée (« Préremplir ») avant ton message ne se prépare plus ; si elle arrive quand même, elle est refusée de même. Une demandée après ton message tient : c'est toi qui la redemandes.
- Ce qui est déjà approuvé, en file ou parti seul (le mode « seule ») n'est pas retenu : il est déjà à l'extension, dont les accusés disent ce qu'il devient (posé, parti, pas servi).

*Pourquoi :* la règle du courrier (0188) vaut pour la même situation dans Teams, sinon sa réponse part après la tienne (audit du 2026-11-05, décision Q16).

*Révise 0188 (en partie : répondre soi-même dans Teams refuse aussi ses réponses en attente), 0189 (en partie : ton message Teams entre dans sa vie dès qu'il part, sans attendre l'extension).*

### 0211 — L'appel sur accord et son échéance : une mécanique dans le contrat, une panne qui se voit

- **Ce qui est commun est dans le contrat du runtime** (`contracts/runtime.py`, avec `DECIDER` et `EXPIRES`) : les délais d'une carte et d'un accord de l'opérateur, le sursis de l'attente en mode pro, les états d'une demande d'appel, `EXPIRER`, où va un appel (`approval_route`), son empreinte (`call_digest`), ses arguments (`call_request`), la garde `still_pending` et le brouillon du refus au nom du délai (`expiry_draft`). `mcp` et `forge` s'en servent, `teams` pour l'échéance. Seul le pur y va : proposer, attendre la décision et émettre restent à chaque plugin, un contrat n'agit pas.
- **Une échéance n'attrape que `Superseded`.** Toute autre erreur remonte au processus : elle s'écrit au journal (`runtime.process_failed`), la santé la voit, et l'ordonnanceur retente après son recul. Une décision déjà journalisée ne lève rien : l'ajout est dédoublonné (`Commit.deduped`), et Teams garde alors le brouillon, qui a pu être accepté.
- **Un refus au nom du délai se signe `délai`, Teams compris.** Un journal plus ancien dit `teams.delai` : Teams reconnaît les deux (`EXPIRERS`), le journal ne se réécrit pas.
- **Une réponse Teams garde ses états** (`attend`, `approuve`, `refuse`, `expire`). Ce sont ceux d'un brouillon, comme au courrier, et `/api/moi` les publie : ne pas les aligner sur ceux d'un appel.
- **Les phrases communes ont leur bloc**, `approvals` dans `persona/voix.yaml` : la Forge ne lit plus les clés de `mcp`. Le résumé d'un appel de service passe aussi par une clé (`mcp.calls.summary`), comme celui d'une app.

*Pourquoi :* la demande était écrite deux fois et son échéance trois, parce qu'un plugin n'en importe pas un autre. Les copies divergeaient déjà, et une `except Exception` cachait toute panne de l'échéance : le processus « réussissait », la santé ne voyait rien, la demande restait « attend » (audit du 2026-11-05, K0-03).

### 0213 — Les portes à clé partagent leur machinerie, pas leur réponse

- **La machinerie est dans `adapters/web/gate.py`** : l'empreinte d'un jeton et sa comparaison en temps constant, la fabrique d'une clé, `SlidingWindow` (une fenêtre par clé : `allow`, ou `blocked`, `fail` et `forgive`), le nettoyage de ce qui arrive du dehors, la borne des dates. Teams, le téléphone, les réveils, les prêts, la console en MCP, les jetons de compte et les cadences du chat s'y servent ; une porte nouvelle aussi, sans recopier.
- **Les portes du transport web (Teams, téléphone, réveils) parlent la même langue** : `GateResult`, `KeyState` et les issues sont dans `ports/gate.py`, et une seule table les dit en HTTP (`GATE_STATUS`). Les prêts et la console en MCP répondent leur statut eux-mêmes.
- **La réponse suit l'exposition de chaque porte, et ne s'uniformise pas.** Ouverte au réseau (Teams, réveils) : une clé absente et une mauvaise clé se répondent pareil, rien ne dit qu'un nom existe. Là où seuls la boucle locale ou un jeton d'opérateur entrent (prêts, console MCP) : un point sans jeton n'existe pas (404), une mauvaise clé répond 401.
- **Le transport web a sa session dans `adapters/web/session.py`** : ses deux cookies, le jeton CSRF, et `account_of` pour les routes HTTP qui ne veulent que le compte. Les WebSocket et les routes qui ont besoin de l'identifiant du jeton lisent encore `Accounts` elles-mêmes ; ce qui fait qu'une session ou un jeton vaut (sa durée, sa révocation, un compte actif) est dans `Accounts.session` et `Accounts.token`, que tous ces chemins lisent.

*Pourquoi :* la comparaison en temps constant, les plafonds de cadence et le nettoyage des entrées sont du code de sécurité ; en quatre à huit copies, une correction faite dans l'une n'atteignait pas les autres. L'audit du 2026-11-05 a d'abord lu les 404 des prêts comme une divergence : ils suivent l'exposition de la porte.

### 0214 — Joindre des fichiers à un mail qu'on écrit, et la copie cachée

- Dans frontendv2, écrire, répondre et transférer peuvent joindre des fichiers et ajouter une copie cachée (Cci). Les routes `POST /api/moi/mail/send`, `reply` et `forward` acceptent alors un `multipart/form-data` : les mêmes champs, les fichiers sous `files`. Sans fichier, elles restent en JSON.
- **La règle vit dans le plugin.** La couche HTTP ne fait que borner le corps pendant qu'il arrive (les pièces, plus 1 Mio) et apporter les fichiers à l'action par son contexte (`ActionContext.files`, jamais au journal). `ecrire`, `repondre` et `transferer` les jugent au même endroit (`_pieces`) : 25 Mo par pièce (la borne de 0172), dix pièces, 50 Mo par mail ; un nom sans dossier ; une sorte qui ne se prend pas pour une structure du mail (`multipart/`, `message/` : `application/octet-stream`). Un transfert auquel on ajoute des fichiers compte aussi, dans les dix pièces et les 50 Mo, celles qu'il reprend (refus dans `forward`, seul à les connaître) ; sans ajout, il reste ce qu'il était, même d'un mail au-delà de ces bornes.
- **Le délai suit le poids.** Python compte le délai d'une socket pour toute l'écriture, pas paquet par paquet : les 30 s d'une commande couperaient un mail lourd. L'envoi SMTP et la copie dans « Envoyés » (APPEND) prennent `max(30 s, taille / 1 Mbit/s)`, le temps de cette écriture. Un serveur muet met donc plus longtemps à se voir (au pire 9 min 30 pour 50 Mio de pièces).
- **Elles sont rangées comme des pièces reçues (0172).** Leurs octets vont en morceaux dans `blobs` ; leur ligne de `parts` a pour propriétaire l'envoi (l'`id` de sa ligne de `sent`, en négatif). `sent.source` ne garde que le texte : une pièce lourde n'y tiendrait pas dans un paquet de MariaDB. Elles comptent dans les 4 Gio, y cèdent leurs octets comme les autres, et partent avec leur envoi quand on oublie son destinataire. Une pièce cédée se dit : le transfert refuse au lieu de partir sans elle.
- **La copie cachée ne se garde pas ici.** Elle va dans l'enveloppe SMTP et dans la copie rangée sur le serveur (« Envoyés ») ; ni dans `sent.source`, ni au journal, ni dans ce que Mika sait de cet envoi : rien ne la relierait à l'oubli de cette personne.
- Joindre demande le niveau qu'envoyer demande déjà : un partage « s'en servir » peut, un niveau inférieur non (403). Retoucher un brouillon d'elle n'a ni pièce ni Cci, car il part tel qu'il est lu ; une réponse reprise de son brouillon, à laquelle tu joins un fichier, part comme ta réponse et retire le sien (0188).
- Teams viendra plus tard : l'extension ne pose que du texte.

*Pourquoi :* envoyer un document est l'une des premières choses qu'on vient faire dans un client de courrier, et il fallait passer par un autre. Une pièce envoyée suit le rangement de celles qu'on reçoit plutôt qu'un second chemin : mêmes bornes, même oubli.

*Révise 0172 (en partie).*

### 0228 — Une adresse venue du dehors se juge par une seule règle

- **Une adresse publique, c'est Internet seulement** : ni la machine elle-même (ses adresses v4 et v6, relues au plus toutes les cinq minutes), ni le port où Mika écoute (même sous une adresse qui n'est pas la sienne : une box qui relaie ce port vers elle), ni le réseau local (la boucle locale, les réseaux privés, le lien local, l'espace partagé d'un opérateur, les plages réservées, la multidiffusion), ni une adresse privée déguisée en IPv6 (correspondance, 6to4, Teredo, NAT64). Toutes les adresses d'un nom doivent passer, et la connexion part vers l'une d'elles, jamais vers une seconde résolution.
- **Trois lecteurs la suivent** : la Forge, à chaque saut d'une requête d'une app (0105) ; les flux, pour l'adresse d'un article à chaque saut et pour la redirection qui quitte l'hôte d'un flux (0037 ; un flux, choisi par un opérateur, garde le droit d'être local) ; l'API par personne, pour les serveurs qu'une personne qui n'est pas opératrice fait joindre, une boîte ou un service MCP (sur leurs adresses : l'hôte s'y donne sans le port).
- **Elle vit dans `adapters/addresses.py`** : `is_global` juge une adresse, `refusal` dit laquelle des trois refuse des adresses déjà résolues (les flux résolvent eux-mêmes, en asynchrone, et redisent le refus sans l'adresse), `check_public` en fait une `ValueError` simple aux mots de la Forge (son journal garde « → ValueError: … »), `resolve_public` résout une fois puis juge ; `LOCAL` et `serving_on` tiennent les adresses de la machine et ses ports. Aucun lecteur ne la recopie.
- **Gardent leur règle à part** : le serveur de recherche du plugin web, un programme lancé dans sa cage (0066) ; et la règle inverse des services MCP en http (`mcp/config.py`, `private_host` : du http seulement vers la machine ou le réseau local, pour que le jeton ne passe pas en clair ailleurs).

*Pourquoi :* trois copies de la règle divergeaient. Les flux et `/api/moi` laissaient passer une adresse NAT64 de la boucle locale ou d'un réseau privé (`64:ff9b::7f00:1`, `64:ff9b::a00:1`), et ne refusaient ni la machine elle-même ni le port de Mika, que la Forge refusait déjà (audit du 2026-11-05, K9-02).

### 0236 — Les en-têtes d'un service ne suivent pas une adresse qui mène ailleurs

- Les en-têtes secrets d'un service qu'une personne a branché (0192) restent scellés, jamais rendus ; laissés vides, ils restent. Mais quand son adresse mène ailleurs — un autre hôte, un autre schéma ou un autre port —, `POST /api/moi/mcp/save` les redemande : 400 sur `secret_headers`, en mots, et rien n'est enregistré, tant qu'on ne les redonne pas ou qu'on ne les retire pas (`clear_headers`).
- Un autre chemin sur le même serveur, ou le port que le schéma sous-entend, ne redemande rien ; un service sans en-têtes non plus. Les retirer ne redemande rien : rien ne part plus.
- La règle se juge sur la fiche relue sous le verrou des réglages (`McpSettingsStore.settle`) : une adresse changée ailleurs entre-temps compte. C'est celle des mots de passe d'une boîte (`_kept_secrets`) : un secret ne part jamais vers un autre serveur.
- L'application Android et frontendv2 le disent sous le champ des en-têtes avant d'envoyer, et offrent de les retirer.
- La console n'est pas ce chemin : une opératrice y règle la fiche entière d'un service par le formulaire des réglages, où un secret vide reste aussi. Elle garde sa règle pour l'instant.

*Pourquoi :* la relecture de l'app Android du 2026-11-17 (R3-02) : changer l'adresse d'un service en laissant ses en-têtes vides, comme l'aide le conseillait, les envoyait au nouvel hôte dès le premier essai. Depuis un téléphone perdu pas encore révoqué, c'était une façon d'emporter le jeton d'un service tiers.

*Révise 0192 (en partie : ses en-têtes suivent son adresse).*

### 0238 — Mika livre son application Microsoft

- Mika livre l'identifiant (client ID) d'une application Microsoft : un client public inscrit dans Microsoft Entra, comptes personnels acceptés (`adapters/mail/config.DEFAULT_APPLICATION`). Ce n'est pas un secret : un client public n'en a pas, et tout logiciel de courrier livre le sien.
- Une boîte Microsoft qui ne déclare pas d'application entre par elle. Ajouter une boîte Hotmail ou Outlook.com ne demande donc que son adresse et son nom, puis « Se connecter à Microsoft ». L'annuaire reste `consumers` par défaut.
- Une instance peut la remplacer par la sienne, gardée dans les réglages, à part des comptes : dans la console, Courrier › Paramètres › Compte Microsoft ; en ligne de commande, `mika mail application <client ID>` (`--defaut` revient à celle livrée).
- Une boîte peut encore déclarer la sienne (`oauth_client_id`), qui passe devant les deux : pour un annuaire Microsoft 365 qui n'admet que ses propres applications. frontendv2 et l'application Android rangent ce champ et l'annuaire sous « Avancé » (`microsoft_app` dans `GET /api/moi/mail/boxes` ; un serveur d'avant, qui ne le dit pas, les fait demander comme avant).
- La connexion gardée dit toujours quelle application l'a délivrée : en changer demande de reconnecter les boîtes qui entraient par elle.
- Mika ne livre toujours l'identifiant d'aucun autre logiciel.

*Pourquoi :* demander à chaque personne, puis à chaque instance, d'inscrire une application dans Microsoft Entra rendait l'ajout d'une boîte Hotmail impraticable : l'inscription exige un annuaire et un compte Azure. Un logiciel de courrier l'inscrit une fois pour tous ses utilisateurs ; Mika fait de même.

*Révise 0166 (en partie : l'application n'est plus celle de la personne, et Mika livre la sienne).*

### 0240 — Son tri lit ce qu'il peut, le reste attend ; le repli ne devine jamais une réponse attendue

- Un relevé fait trier par le modèle au plus `triage_per_poll` mails (« Mails triés par le modèle », 5) ; seuls les appels faits comptent : un envoi en masse n'y prend plus de place.
- Au-delà, un mail n'est ni deviné ni remarqué : il reste sans accusé (`MailPort.waiting`), et le relevé suivant vient deux minutes après au plus, tant qu'il en reste. À 0, le tri par le modèle est coupé : tout se devine, rien n'attend.
- Le repli (un tri en panne, retenu par le quota, une réponse illisible, ou coupé) devine l'importance, jamais une réponse attendue ni une émotion.
- Qui a jugé chaque mail est au journal (`MailNoticed.triage` : le modèle, le repli, un envoi en masse). L'API par personne le dit (`triage` : `read`, `guessed`, `bulk`, et `waiting` pour un mail relevé qui attend son tri) ; frontendv2, l'application Android et la fiche de la console le montrent.

*Pourquoi :* le 2026-11-17, le premier relevé d'une boîte Hotmail a rendu dix mails ; le modèle a trié les cinq premiers, dont un envoi en masse qui prenait une place sans appel, et le repli a jugé les cinq autres. Trois notifications Qonto sont sorties « réponse attendue » : un « Une question ? » en pied de page suffisait au repli. Le modèle, lui, avait jugé la quatrième « notification automatique », sans réponse. Le même arriéré revient à chaque réveil et après chaque coupure.

*Révise 0147 (le repli ne devine plus la réponse attendue).*

### 0243 — Les consignes de tri d'une boîte : ranger, prévenir, juger

- Chaque boîte a ses « Consignes de tri » (`MailAccount.triage_instructions`), à côté des consignes d'écriture : du texte libre de qui la règle (Paramètres › Mail, la console, l'application). Son tri les lit, avec les dossiers de la boîte, pour chaque mail qui arrive dans un dossier relevé ; un mail reçu n'en est jamais une.
- Le modèle rend alors deux champs de plus : `dossier` (où ranger) et `prevenir`. Ces consignes guident aussi l'importance et la réponse attendue. Une boîte qui en a fait lire ses envois en masse au modèle : ce sont eux qu'on range le plus souvent.
- Ranger : un dossier qui existe dans la boîte, jamais ses brouillons ni ses envoyés. Le geste suit l'événement (`MailNoticed.file_to`), sur le serveur, comme `email_tidy` : réversible, jamais une suppression. Elle n'en parle plus (« déplacé par elle »). Un refus du serveur laisse le mail où il est.
- Prévenir : le mail devient important (au moins « Important à partir de »), et elle l'annonce comme tout mail important d'une de tes boîtes (`MailNoticed.alert`). Un mail dont elle doit prévenir et qu'elle range reste à dire.
- Seul le modèle les applique : le repli (panne, quota) ne range ni ne prévient. L'API par personne dit `her.alert` et `her.filed` (le dossier, tant que le mail y est) ; la liseuse de frontendv2 et de l'application, et la fiche de la console, le disent.

*Pourquoi :* « trie les pubs dans PUB, prépare les réponses si nécessaire, avertis-moi des notifications liées à XXX » (2026-11-17) : les consignes d'une boîte ne servaient qu'à écrire, et son tri ne connaissait ni tes critères ni tes dossiers. Préparer les réponses existait déjà (la règle de la boîte, « Préparer d'elle-même »).

### 0247 — Elle relève ses boîtes quand elle veut

- Un outil, `email_fetch` (« Relever tes boîtes maintenant »), va chercher sur le serveur ce qui vient d'arriver dans les dossiers relevés des boîtes de qui est en face, ou dans un dossier qu'elle nomme, et le lui montre aussitôt.
- Ce qui arrive dans un dossier relevé est trié et remarqué comme à chaque relève : l'outil demande la relève (`email.poll_asked`, `by` vide : c'est elle), qui suit tout de suite. Un dossier seulement consulté ne lui rend rien à remarquer.
- C'est un outil de lecture, offert comme `email_list` à qui a une boîte ici. Sans rien de nouveau, rien ne s'écrit au journal.

*Pourquoi :* « regarde si le mail de Paul est arrivé » : elle ne voyait que le dernier relevé, jusqu'à dix minutes plus tôt, et un dossier jamais synchronisé restait vide pour elle.

### 0248 — Elle crée un dossier en rangeant

- `email_tidy` déplace aussi vers un dossier qui n'existe pas encore quand elle le dit (`create`) : il est créé sur le serveur, sous la racine des dossiers de la boîte (celle que dit `NAMESPACE`), « / » séparant un sous-dossier, puis abonné pour que les autres clients le montrent. Elle y range sous le nom que le serveur lui a donné (« INBOX.Factures.EDF »).
- Sans `create`, un dossier inconnu reste refusé, avec la liste des dossiers de la boîte : une faute de frappe ne crée rien.
- Ses consignes de tri (ADR 0243) ne créent jamais de dossier : seul un geste d'elle, sous les droits de `email_tidy`, en crée un. Supprimer ou renommer un dossier ne lui est pas donné.

*Pourquoi :* « range ces factures dans un dossier Factures » échouait quand le dossier n'existait pas : il fallait le créer dans un autre client.

### 0249 — Tout garder en local, sinon chercher sur le serveur

- Chaque boîte a une case « Tout garder en local » (`MailAccount.keep_all`, décochée par défaut). Cochée, ses dossiers, sauf les indésirables et la corbeille (`ports.mail.ASIDE`), sont tenus à jour à chaque relève, et leur historique se télécharge petit à petit, les plus récents d'abord, qu'elle dorme ou non (le processus `email.keep`, par passages de quelques secondes : le verrou de la boîte se rend vite). L'historique, c'est chaque UID du serveur qui n'est pas ici, sous le plancher de la lecture précédente (`folders.floor`) ; un dossier allé jusqu'au bout est complet (`Folder.complete`).
- Ce qui se télécharge ainsi, et ce qu'une recherche ramène, n'est jamais trié ni remarqué : son tri ne lit que ce qui arrive dans les dossiers relevés, et au premier relevé d'un dossier seulement la fenêtre de relève (deux jours). Ce qui vient d'avant n'est marqué « rendu » que dans un dossier relevé, sous ce que la relève a atteint : au-dessus, ou dans sa copie d'un autre dossier (Gmail), un mail qui vient d'arriver reste à trier.
- Un correspondant oublié n'en revient pas : l'oubli retient l'empreinte de son adresse et son instant (`forgotten_people`, jamais l'adresse), et ce qu'il avait écrit avant, ou ce qu'on lui avait écrit, ne se garde plus, ni ne se compte dans une recherche.
- Décochée, tant que le téléchargement n'est pas fini, ou pour un dossier nommé qui ne l'est pas (la corbeille), `email_search` cherche aussi sur le serveur (pas une recherche des non-lus, qui viennent d'arriver) : chaque mot dans l'objet, l'expéditeur ou le texte, dans le dossier nommé ou dans tous sauf `ASIDE`. Il ramène les plus récents qui manquent ici jusqu'à la page demandée, dit combien attendent encore, et les dossiers où il n'a pas pu chercher. Une liste dit le plus ancien mail gardé ici, ou que tout l'est.

*Pourquoi :* une recherche ne voyait que ce qui avait été relevé, deux jours au premier relevé : « la facture d'EDF de l'an dernier » n'existait pas pour elle, et seule la console chargeait plus ancien. Trier ce qui vient d'avant ferait juger par le modèle des milliers d'anciens mails, et les lui ferait remarquer comme s'ils arrivaient (2026-11-18).

*Révise 0168 (elle cherche aussi sur le serveur).*

### 0300 — Teams : les réactions et les photos de profil

- **Les réactions** (👍, ❤️…) d'un message partent avec lui depuis l'extension, et repartent quand elles changent : qui a réagi et comment. Mika les **voit quand elle lit** le message — le tri, la préparation d'une réponse, ses outils de lecture les montrent à côté du texte —, mais **une réaction ne déclenche jamais rien** : ni remarque, ni tri, ni réponse ; elle est lue la prochaine fois que le message l'est.
- **Les photos de profil** : la page Teams les sert à qui est connecté (`/api/mt/part/<région>/beta/users/<moi>/profilepicturev2/<personne>`, sondé le 2026-11-22) ; l'extension télécharge celle de chaque personne dont un profil part (ADR 0298 : jamais pour une conversation exclue, rien pendant une pause), petite (64 px), une fois, puis seulement quand Teams dit qu'elle a changé (`avatarETag`). Les images de groupe de même, pour les conversations de groupe.
- Elles sont gardées avec Teams sur le serveur, servies derrière la connexion à qui voit la personne ou la conversation, et effacées avec la personne (l'oubli) ou le compte.
- Les écrans (fil Teams, conversations, annuaire, Contacts) montrent la photo à la place des initiales et les réactions sous la bulle : maquettés d'abord (`frontendv2/maquette/`), validés, puis codés.

*Pourquoi :* « tu penses qu'il est possible d'ajouter les photos de profil et les émoticônes de message ? » ; « quand Mika analyse un message ou veut le lire, elle doit voir la réaction des gens, oui ; après, un pouce ne déclenche pas une analyse réelle ».

### 0301 — Teams : envoyer sans ouvrir la conversation, par le worker de Teams

- Le nouveau Teams fait ses appels au service de chat dans son worker : la page n'en voit jamais l'authentification, et l'extension n'envoyait que par la zone de saisie, la conversation ouverte. La page passe au worker des commandes GraphQL en texte JSON ; envoyer est `mutation autoSendMessage`. L'extension **rejoue cette commande** (modèle capté lors d'un vrai envoi dans la page, sans son texte ; identifiants, heure et texte refaits ; numéro de requête au-dessus du compteur) : **le worker envoie lui-même**, avec sa propre connexion, sans que la conversation soit ouverte. Aucun jeton n'est jamais lu ni touché.
- Seulement pour les tête-à-tête et les groupes ; un canal, une réunion, ou l'absence de modèle passent comme avant (le service de chat, puis la zone de saisie, la conversation ouverte). La réponse du worker dit l'issue : un refus explicite (rien n'est parti) laisse la voie suivante, le service de chat puis la zone de saisie ; un silence de dix secondes, ou une réponse qui porte à la fois des erreurs et un résultat, est une issue douteuse, jamais renvoyée — jamais deux envois (le worker et le service de chat reprennent le même identifiant de message, que Teams dédoublonne).
- Ça repose sur le fonctionnement interne de Teams : une mise à jour peut le casser ; la zone de saisie reste la voie sûre, et le diagnostic dit laquelle a servi.

*Pourquoi :* « quand la conversation n'est pas ouverte on ne peut pas envoyer de message ? » ; « essaye de voir si tu trouves une astuce pour 2, test sur Albert » ; « oui ajoute ». Sondé et essayé le 2026-11-22 sur Albert (essai 5 parti, conversation fermée).

*Révise 0251 (en partie : la voie d'envoi).*

*Révisée par 0305 (en partie : un envoi peut porter une citation).*

### 0302 — Un rangement se voit aussitôt ; le serveur range la sélection en une session

- **Les clients n'attendent pas le serveur** pour montrer un rangement (frontendv2 et l'app Android ; liste, liseuse, sélection) : un mail archivé, mis à la corbeille ou déplacé quitte la liste tout de suite, la liseuse revient à la liste ; lu, non lu, suivi se posent aussitôt. Une lecture de la liste partie avant la réponse ne le remontre pas. Ce que le serveur refuse revient, et le refus se dit.
- **Archiver, la corbeille et déplacer rangent une sélection en une session IMAP par boîte** (`MailPort.move_many`) : chaque dossier de départ ouvert une fois, un `MOVE` par mail, qui garde son UID d'arrivée. Avant, chaque mail ouvrait sa session (connexion, login, dossier), parfois derrière un relevé : plusieurs secondes par mail. Une connexion coupée en route refuse ce qui restait, pas ce qui est fait. Marquer lu l'était déjà (`mark_seen`) ; non lu et suivi restent mail par mail.
- **Déplacer une sélection dans un dossier** passe par « Ranger la sélection » (`email.ranger`, geste `deplacer`) : une action pour toute la sélection, comme archiver et la corbeille, et non plus « Déplacer » mail par mail. `email_tidy` (ses outils) range de même.

*Pourquoi :* « quand je supprime un email ce n'est pas instantané, il n'y a pas cet effet de c'est fait directement » ; puis « oui aux deux » (Android, la session unique), le 2026-11-22.

*Révise 0200 (en partie : déplacer une sélection se fait en une action, en un lot).*

### 0305 — Teams : Mika cite le message auquel elle répond

- Quand un envoi répond à un message précis (le `reply_to` de son brouillon), il le **cite**, comme on le fait dans Teams avec « Citer » : dans un **groupe**, toujours ; dans un **tête-à-tête**, seulement si d'autres messages sont arrivés après celui auquel elle répond — sinon elle répond au dernier, et la citation ne dirait rien. Ni dans un canal, ni dans une réunion (une réponse y est un fil, pas une citation).
- Le serveur la met dans la boîte d'envoi de l'extension (`OutboxItem.quote` : l'identifiant du message chez Teams, son auteur — identifiant et nom —, son heure, un extrait de 160 caractères), seulement pour un message dont il a l'**identifiant de service** (l'heure d'arrivée, le seul que Teams sache citer) et un auteur reconnaissable ; sinon l'envoi part sans citation.
- L'extension l'écrit comme Teams (relevé le 2026-11-22, essai 8 chez Albert) : un bloc `<blockquote itemtype="http://schema.skype.com/Reply" itemid="<message>">` (l'auteur, l'heure, l'extrait) avant le texte, et, par le worker, l'entrée `computed.quotedMessages` (`messageId`, `sender`, `time`). Par le worker et par le service de chat ; par la zone de saisie, le message part sans citation. Essai 9 : une citation construite, la conversation fermée, s'affiche comme celle de Teams.
- Un envoi de la page qui cite ne devient jamais un modèle d'envoi (ADR 0301) : rejoué, il recollerait sa citation à chaque envoi.
- **Quand c'est toi qui cites** (frontendv2, l'application : « Citer » sur un message, comme dans Teams), la citation part toujours, dans un tête-à-tête aussi : c'est un geste, pas une règle de Mika (un brouillon qui a un auteur, `TeamsStore._quote_in(asked=…)`).
- **Les citations reçues** sont gardées à part du texte du message : l'extension (0.8.3) sépare le bloc de Teams (`quote` : le message cité, son auteur, un extrait), le serveur le range avec le message (`messages.quote`, migration `b8e4c2a7d915`) et retrouve le message cité quand il l'a (`ref`). L'API le rend (`quote`) ; frontendv2 et l'application montrent la carte de Teams au-dessus du texte, qui mène au message cité. Mika le lit devant le texte, partout où elle lit un message (« (en réponse à Sophie : « … ») », `teams.quote` dans sa voix). Ce qui était là avant garde sa citation en ligne dans le texte : recharger l'historique la sépare (« effacer plutôt que convertir »).
- Pas de maquette : « pas besoin de maquette pour un truc aussi petit, calque-toi sur le fonctionnement de Teams » — « Citer » au survol d'un message (au doigt, en le touchant ; dans l'application, un appui long), la carte au-dessus du champ avec son ×.

*Pourquoi :* « et pourquoi on n'implémenterait pas la citation ? » — dans un groupe qui parle de plusieurs choses, une réponse qui ne dit pas à quoi elle répond se perd.

*Révise 0301 (en partie : un envoi peut porter une citation).*

### 0307 — « Corriger » : les fautes, sans changer les mots

- Dans le champ de Mail et de Teams (frontendv2, l'application), à côté de « Préremplir avec Mika », **« Corriger »** corrige les fautes de ce que tu écris : orthographe, accents, accords, conjugaison, homophones, ponctuation et ses espaces. Jamais les mots : rien d'ajouté, de retiré ni de remplacé, pas de reformulation, le ton, les abréviations, les noms, les liens et la mise en forme tels quels.
- Le texte corrigé **remplace** le tien aussitôt ; un message dit combien de fautes ont été corrigées, avec « Annuler » pour revenir à ton texte (« Aucune faute » sinon).
- Un **nouveau rôle de modèle**, `correct` (« corriger les fautes », famille « écriture », dans Réglages › Intelligence), **facultatif** : sans modèle à lui, le bouton reste éteint et dit pourquoi (`GET /api/moi` → `correct`) ; aucun repli sur un autre rôle.
- `POST /api/moi/correct` (`app/me/writing.py`) : un appel au premier plan (tu attends), sans persona (ce n'est pas elle qui parle), sa consigne dans `persona/voix.yaml` (`correct.system`), une correction à la fois et vingt par minute par compte. Rien n'est gardé, ni au journal ni ailleurs que dans le registre des appels de modèle.
- **Les mots ne changent pas, quoi que le modèle rende** : sa réponse, débarrassée de ce qu'il met autour (guillemets, bloc de code), est alignée sur ton texte phrase par phrase puis mot par mot, et seules s'appliquent les corrections qui ne touchent pas aux mots — accents, casse, ponctuation et ses espaces, un mot collé, coupé ou redoublé, un mot remplacé par une forme proche (« renvoi » → « renvoie »), une élision (« ses » → « c'est »). Un mot ajouté ou retiré, un chiffre changé, un mot remplacé par un autre (« lundi » → « mardi »), un préambule sont écartés et comptés (`refused`) ; s'il en écarte plus qu'il n'en corrige, rien n'est posé. Une réponse incomplète (un refus du fournisseur, un plafond atteint) ne l'est jamais, même en partie. L'alignement est linéaire sur un long passage et se fait hors de la boucle du serveur.

*Pourquoi :* « peux-tu ajouter un bouton corriger pour corriger les fautes sans modifier les mots, dans Teams et Mail ? avec une nouvelle catégorie dans les paramètres pour la sélection du modèle IA » (le 2026-11-23). Choisis le même jour : remplacer avec « Annuler » plutôt que montrer puis accepter ; web et Android ; rien sans modèle choisi. La relecture du même jour a montré qu'une garde sur la ressemblance d'ensemble laissait passer « 300 » → « 500 » ou un « pas » retiré : d'où l'alignement mot par mot.

### 0309 — L'agenda : ceux du système et ceux qu'on branche, chacun à quelqu'un, avec son tableau de droits

- **Des comptes d'agenda, chacun à quelqu'un** (la règle des boîtes et de Teams : à toi, ou à une personne qui a un compte ; pas de compte « à elle » : son agenda est sa mémoire, plus bas), qui portent un ou plusieurs agendas. Cinq sortes : **le système** (dans le serveur de Mika : chaque personne qui a un compte a « Mon agenda », et en crée d'autres), **Google Agenda** (OAuth 2 : un client « Application de bureau » par serveur, réglé dans la console ; Google refuse le code d'appareil pour l'agenda, on colle donc l'adresse de retour `http://127.0.0.1/…` après le consentement, ou la redirection se fait seule quand le serveur a une origine HTTPS), **Outlook.com / Microsoft 365** (Microsoft Graph, code d'appareil, l'application Microsoft du courrier, ADR 0238), **CalDAV** (Outlook pro par DavMail, iCloud, Nextcloud, Fastmail) et **l'abonnement iCal** (une adresse `.ics`, en lecture seule).
- **Le monde, pas sa vie** : les événements vivent dans leur base, hors du journal, comme le courrier et l'annuaire ; ceux du système y font foi, ceux d'un fournisseur en sont la copie, relue par une synchronisation incrémentale quand le fournisseur le sait, dans une fenêtre de 90 jours derrière à un an devant. Une écriture part tout de suite chez le fournisseur, puis la copie se relit. L'oubli atteint la base ; chaque écriture se signale aux écrans en direct (ADR 0308).
- **Partager** un agenda : seul son propriétaire, à une personne qui a un compte, aux trois niveaux de Mail et Teams (Lire · Lire et préparer · S'en servir). Un partage dans Mika n'est pas un partage chez Google ou Microsoft.
- **Un tableau de droits par agenda** (Qui × Par où × Quand, ADR 0133–0134), comme un service : lire ; ajouter, modifier, supprimer ; répondre aux invitations ; ce qu'elle en garde. Son propriétaire le règle dans son espace ; la console le montre, un opérateur le règle dans Réglages › Droits. Masquer un agenda le retire aussi à Mika ; le décocher dans la vue ne change que l'affichage.
- **Ce qu'elle en fait** : ses outils (lire une période, trouver un créneau, créer, modifier, supprimer, répondre à une invitation), offerts à qui a un agenda ou en reçoit un partage ; écrire est une capacité, après le commit, avec ou sans accord selon le tableau. Elle sait la journée de la personne en face (aujourd'hui et demain, en tête-à-tête, texte venu du dehors : cité) ; elle la prévient avant un rendez-vous (une initiative que l'arbitre juge ; délai réglé par agenda : Mika 30 min avant pour le système, coupée par défaut chez un fournisseur, rien pour un abonnement) ; elle propose d'ajouter un rendez-vous décidé dans la conversation (la carte d'accord) ; elle prépare la réponse à une invitation, toujours avec l'accord de la personne.
- **Les invitations entre personnes qui ont un compte** (agenda du système) arrivent dans l'agenda de l'invitée, sans e-mail ; un événement refusé disparaît de la grille.
- **L'agenda de Mika** n'est pas une seconde copie : ses promesses datées et ce qu'elle voit venir se montrent comme un agenda, en lecture seule, tirés de sa mémoire ; une personne n'y voit que ce qui la concerne, jamais ce qu'une autre lui a confié ; la console voit tout, par personne. On le corrige en le lui disant.
- **L'opérateur** voit tous les agendas dans la console (Échanges › Agendas, choix par personne) : il lit (un événement privé reste « Occupé »), synchronise, retire un partage, déconnecte ; il ne crée, ne modifie ni ne répond jamais à la place de quelqu'un. Chacun branche ses comptes dans son espace (frontendv2, l'application).
- **Où ils vivent (lot 0, 2026-11-23).** Le port `ports/agenda.py` (ses types, le magasin `AgendaPort`, un fournisseur `CalendarProvider`, les fournisseurs par sorte `AgendaProviders`) ; la base `agenda` (`agenda.db`, ou `mika_agenda` : `adapters/agenda/models.py`, sa révision dans `app/migrations/agenda/`), sauvegardée comme l'annuaire ; son magasin `adapters/agenda/store.py` (le port `agenda`), le fournisseur Système `adapters/agenda/system.py`, les fournisseurs par sorte et les comptes des réglages `adapters/agenda/__init__.py::Providers` (le port `agenda_providers`, où iCal, CalDAV, Google et Microsoft viendront) ; les comptes dans les réglages (`adapters/agenda/config.py::AgendaConfig`, sous la clé `agenda` d'`app/settings.py` ; le mot de passe et l'adresse d'un abonnement, qui ouvre l'agenda à qui la connaît, scellés) ; le plugin `plugins/agenda/` et son processus `agenda.sync`. Le compte du système d'une personne est `moi:<sa clé>`, à elle, sans rien régler ; un agenda se nomme `<compte>~<clé courte>`, tirée de l'identifiant du fournisseur ou de son empreinte — jamais une adresse, puisque ses réglages (partages, masqué, rappel) sont journalisés avec les paramètres du plugin. Pas encore de compte « à elle » (la question 2 de la conception). La récurrence suit la RFC 5545 (RRULE, EXDATE, RDATE, RECURRENCE-ID), développée par `python-dateutil` à la même heure de son fuseau ; les instants sont en UTC avec le nom du fuseau, une journée entière reste une date. Une invitation du système est une copie dans « Mon agenda » de l'invitée, déduite des lignes de l'organisatrice dans la même écriture ; la supprimer de son agenda, c'est la refuser ; elle ne se modifie que chez qui l'organise. Chaque écriture de la base se dit aux écrans en direct (sujet `agenda`), que le contrat de l'API par personne recevra avec elle (lot 4).
- **L'oubli** (lot 0) : oublier une adresse (`mail:<adresse>`) ou une personne (sa clé, qui la désigne dans les événements du système) la retire des participantes de chaque événement ; un événement qu'elle organisait garde son créneau, vidé de ce qu'elle y avait écrit (titre, lieu, description, lien, elle-même) — il se montre « Occupé », comme un événement privé, pour que Mika sache encore qu'on n'y est pas libre. L'empreinte de l'adresse et l'instant de l'oubli restent : une synchronisation ne la ramène ni parmi les participantes, ni ses mots, dans ce qui a été créé avant ; ce qui naît après revient. Jamais dans l'agenda d'un compte à elle (le compte de cette adresse, son compte du système, un compte à son nom) : comme sa boîte, il est à elle et part avec son compte. Écarté : effacer l'événement qu'elle organisait, comme un mail qu'elle a écrit — Mika croirait libre un créneau où l'on ne l'est pas.
- **L'abonnement iCal et CalDAV (lot 1, 2026-11-23).** Une seule lecture et une seule écriture de l'iCalendar (`adapters/agenda/ics.py`, la bibliothèque `icalendar`, une dépendance du moteur comme `python-dateutil`), partagées par les deux ; rien n'est gardé tel quel (`Event.raw` reste vide : une adresse oubliée n'y survivrait pas), chaque écriture relit donc la ressource chez le serveur et n'y pose que ce qui change — sur sa dernière version, si bien qu'un conflit (412) ne vient que d'une écriture d'ailleurs entre la lecture et l'écriture ; il se dit en mots, comme un événement disparu, et la copie se relit (`plugins/agenda/sync.py::reread`). Un VTIMEZONE propre au fichier se lit par ses règles à lui et reçoit le fuseau IANA aux mêmes décalages, que la récurrence suit ; une heure flottante se lit dans le fuseau de l'agenda. Un abonnement est un seul agenda, à la clé fixe `abonnement` (une adresse secrète réinitialisée garde ses réglages) ; son adresse ne se range ni dans la base ni dans une erreur ; au-delà de 10 Mo il n'est pas lu, la copie d'avant reste. CalDAV tient tout ce qui vient après le début de la fenêtre, sans borne devant (un `sync-collection` ne redit pas ce qui entre dans la fenêtre en glissant) ; une ressource changée est redonnée en entière (`SyncBatch.replaced`). « Celui-ci et les suivants » écrit la suite (une ressource neuve, un nouvel UID) avant de couper la série, et la retire si la coupe échoue. Une invitation ne se modifie que chez qui l'organise (ses rappels et « occupé » restent à l'invitée) ; la supprimer de son agenda, c'est la refuser ; répondre est refusé en mots sur un serveur qui ne transmet pas la réponse à l'organisateur (sans `calendar-auto-schedule`, comme Radicale) : Mika ne dirait pas « j'ai accepté » à quelqu'un qui ne le saura pas. Ce que Mika a mis dans un agenda branché reste marqué dans la base quand le fournisseur le redit sans la marque — elle n'est jamais écrite chez lui (la référence d'une conversation partirait chez les invités). Une redirection ou une adresse donnée par le serveur qui quitte l'hôte du compte ne mène qu'à une machine publique (la règle d'`adapters/addresses.py`) ; le mot de passe ne part que vers cet hôte ou un hôte de son domaine (iCloud répond d'un autre nom). L'hôte d'un compte (`server_host`) est ce que l'API par personne vérifiera (Internet seulement, pour qui n'est pas opératrice). Une erreur d'un fournisseur se range telle qu'il la dit.
- **Google et Microsoft (lot 2, 2026-11-23).** Leur connexion (le jeton de renouvellement) est scellée dans les réglages à part des comptes (`agenda_oauth`, par compte et par sorte), comme celle d'une boîte ; elle part avec son compte, ou quand il change de sorte ; révoquée ou expirée, elle n'est plus présentée et le compte est « à reconnecter », en mots. **Microsoft** : le code d'appareil du courrier, réutilisé (`adapters/mail/oauth.py::MicrosoftSignIn`, une instance à part), à la portée de Graph (`Calendars.ReadWrite`, `offline_access`) : un jeton à part de celui d'une boîte IMAP, par l'application de l'instance (ADR 0238) ou celle du compte, dans son annuaire. **Google** : OAuth 2 avec PKCE, par une application Google du serveur (un client « Application de bureau », son secret scellé, réglée par un opérateur : `mika agenda google`, puis la console) ; sans elle, brancher Google est refusé en mots ; le parcours se commence (l'adresse de consentement, un retour en boucle locale) et se finit en collant l'adresse de la page qui n'a pas pu s'ouvrir, ou son code seul — le `state` et qui a commencé sont vérifiés, la case de l'agenda doit avoir été cochée ; un client « Application Web » revient lui-même à l'origine HTTPS du serveur (`/api/moi/agenda/google/retour`, la route du lot 4). Le réseau ne va qu'aux hôtes de Google et de Microsoft : un lien qu'une réponse donnerait ailleurs n'est pas suivi. Google se relit par `syncToken` (tout ce qui finit après le début de la fenêtre, sans borne devant ; `410`, tout relu), une série en une ligne et ses exceptions ; l'identifiant de Google de la série tient lieu d'UID (un événement supprimé ne dit que lui). Graph se relit par le delta de la vue d'un agenda sur la fenêtre et un mois de plus (relue quand la fenêtre a glissé au-delà, ou que Graph perd l'état) ; une vue ne rend jamais la série : **la copie garde chaque occurrence d'une série Outlook comme une ligne** (sa série, son `originalStart`), et la règle (`patternedRecurrence` ↔ RRULE) se lit sur la série quand on l'écrit — ce qu'Outlook ne sait pas est refusé en mots ; une série créée se rend par sa première occurrence, la seule marquée de Mika. Chaque écriture relit l'événement chez le fournisseur et n'envoie que ce qui change, avec `If-Match` (un 412 se dit en mots) ; « celui-ci et les suivants » crée la suite d'abord puis coupe la série d'avant (UNTIL chez Google, la veille chez Graph), et retire la suite si la coupe échoue ; une invitation ne se modifie que chez qui l'organise (sauf si Google le permet aux invités), la supprimer la refuse ; répondre prévient l'organisateur (`sendUpdates`, `sendResponse`, sauf s'il n'en demande pas). Un lien de visio donné va dans la description : chacun ne pose que les siens. Rien n'a été essayé contre les vrais Google et Microsoft : de faux serveurs qui suivent leur documentation (`tests/fixtures/google_calendar.py`, `tests/fixtures/graph_calendar.py`).
- **Ce qu'elle en fait en conversation (lot 3a, 2026-11-23).** Le tableau de chaque agenda est une septième sorte de tableau du moteur commun (`vocab.access.AgendaRule` : lire ; ajouter, modifier, supprimer — non, avec accord, seule ; répondre aux invitations — non, avec accord ; ce qu'elle en garde), derrière une première porte, son propriétaire et ses partages : un agenda sert à son propriétaire reconnu, en tête-à-tête (un compte « à toi », à une de ses propriétaires), à elle seule au travail, et à qui il est partagé, à son niveau — jamais masqué ni sous un compte décoché, jamais dans un salon ni pour une inconnue. Sans réglage : son propriétaire, quand elle lui répond, lire, écrire et répondre avec son accord (elle en garde un souvenir) ; d'elle-même, lire ; elle seule, lire et répondre avec accord ; personne d'autre. **Un partage ajoute la ligne de la personne** (lire ; lire et préparer : écrire, sur l'accord du propriétaire, sans répondre ; s'en servir : écrire et répondre, sur son accord à elle) et reste un plafond. Un tableau réglé (par son propriétaire, ou par un opérateur dans Réglages › Droits) se range dans les réglages (`agenda_droits`) et se lit à chaque épisode ; partager y pose ou y retire la ligne de la personne. Son nom désigne la personne en face même quand elle est une des propriétaires (le moteur ne lit une propriétaire que par « toi » ; l'agenda du système d'une opératrice est à son nom). **Ses outils** (`agenda_list`, `agenda_events`, `agenda_free`, `agenda_create`, `agenda_edit`, `agenda_delete`, `agenda_respond`), offerts à qui a un agenda ou en reçoit un partage, quand elle lui répond (pas en prenant la parole : ses rappels et les invitations sont le lot 3b) ; ce qu'ils rendent vient du dehors, cité ; un événement privé d'une autre personne se lit « Occupé ». **Écrire est une capacité** (`agenda.write`) : un aperçu, dont l'empreinte porte l'état de l'événement touché (changé ailleurs entre-temps, l'accord est refusé ; un partage retiré ou baissé entre-temps le bloque) ; seule, elle part aussitôt et l'outil attend qu'elle soit écrite pour le dire ; sinon la carte de la personne en face, ou, pour « lire et préparer », celle du propriétaire (son chat, sinon la console : À valider). Ce qu'elle ajoute porte sa marque et la référence de la conversation (`chat:<adresse>:<message>`) ; ce qu'elle a proposé et ce que c'est devenu (attend, accepté, refusé, fait, raté, avec les mots du fournisseur) s'écrit au journal (`agenda.written`, des contenus) et revient dans son prompt. **Elle sait la journée** de la personne en face : aujourd'hui et demain, ce qui est en cours, dans ses agendas à elle — pas ceux qu'on lui partage, qui sont la journée d'une autre et se lisent par ses outils —, borné et cité, avec la consigne de proposer d'ajouter un rendez-vous décidé dans la conversation, sans insister. Une carte d'agenda n'a pas encore d'échéance : la proposition attend sa décision (le lot 3b dira sa fin).
- **Ce qu'elle en fait d'elle-même (lot 3b, 2026-11-23).** Un processus (`agenda.watch`) relit la base chaque minute. **Ses rappels** : un rendez-vous dont « Mika te le rappelle » est dû (le choix de l'événement, sinon celui de l'agenda : 15, 30, 60 min avant, ou la veille au soir à 20 h ; une journée entière, seulement la veille) devient une initiative **due** (`agenda.REMIND`, dans `agency.OWED` : un rappel demandé, en réglant l'agenda plutôt qu'en mots — ni le plafond du jour ni la retenue envers qui ne répond pas), vers l'adresse où joindre la personne à qui est l'agenda, sur le sujet de cette occurrence ; l'arbitre la juge comme les autres (endormie, elle attend : sa preuve reste sous la barre de réveil). Une fois par occurrence — déplacée, c'en est une autre ; jamais après son début, ni pour un refusé ou un annulé ; seulement si la ligne « quand elle te parle d'elle-même » du tableau le laisse lire devant cette adresse. Elle compose elle-même, le rendez-vous sous les yeux (cité) ; dit, il ne revient plus ; journalisé (`agenda.reminder_due`, `reminder_dropped`, et l'énoncé qui le portait) sans titre ni lieu. **Les invitations préparées** : une invitation qui attend sa réponse, dans un agenda où la ligne « elle seule, au travail » laisse répondre, appelle une tâche — une seule — qui lit l'invitation et ce qui tombe en même temps dans les agendas de la personne invitée (eux seuls) et propose sa réponse (oui, peut-être, non ; un mot ; pourquoi, pour la personne seule), **toujours sur son accord**, quoi que dise le tableau : sa carte dans son chat, et la console. Si elle répond elle-même entre-temps (dans l'écran, chez le fournisseur), la proposition tombe : « Répondu autrement », comme pour Teams (ADR 0199). **Une proposition qui attend** tombe quand son rendez-vous commence, disparaît ou est annulé (refusée au nom du délai) ; la carte du chat, elle, ne vaut que deux heures (`card_within_us`, jamais au-delà du début du rendez-vous) : passé ce délai, la proposition reste à décider dans l'Agenda jusqu'au début du rendez-vous — la décision de la maquette, « la carte du chat expire, la proposition reste dans l'Agenda ». **Écrire** : `agenda_create` et `agenda_edit` invitent des adresses (une personne qui a un compte, dans un agenda du système, reçoit l'invitation dans le sien) et posent ou retirent « Mika te le rappelle » sur l'événement — gardé dans la base seulement (`events.remind`), jamais chez le fournisseur. **L'agenda de Mika** est une lecture de sa mémoire par sa porte (`app/her_agenda.py::her_agenda`, que l'API par personne et la console appelleront) : ses promesses datées, les moments de la vie des gens (une date qui revient chaque année à sa prochaine fois) et ce qu'elle voit venir, chacun avec d'où il vient (« Elle te l'a promis mardi 17 novembre », la conversation, la référence de l'élément) ; pour une personne, ce qu'elle lui a promis et ce qu'elle lui a raconté elle-même — jamais ce qu'une autre a confié, rien de secret, chaque élément passé au verdict de sa mémoire devant elle seule ; pour la console, tout, avec à qui. Écarté : un rappel « prévient » (`INFORMS`) plutôt que dû — le plafond du jour aurait pu taire un rendez-vous ; une tâche d'invitation sans sa mémoire, comme Teams — la raison d'une réponse est souvent ce que la personne lui a dit, et rien ne part sans son accord, comme pour un courrier.
- **L'API par personne (lot 4, 2026-11-24).** `/api/moi/agenda/…` (`app/me/agenda.py`, `docs/protocole-moi.md` § 13) : ses agendas (les siens, ceux qu'on lui partage, ses abonnements, l'agenda de Mika vu par elle), une période, un événement, chercher, ses invitations et ce que Mika propose ; ses comptes (Paramètres › Agendas : Google en collant l'adresse de retour ou par la redirection directe, `/api/moi/agenda/google/retour` ; Microsoft par le code d'appareil, son attente poussée ; CalDAV essayé puis choisi ; iCal), leurs réglages et leur tableau de droits. Chaque écriture est une action du plugin (`plugins/agenda/actions.py`), au nom de la personne, qui relit elle-même ce qu'elle a de l'agenda — l'API dit 404 avant. **Un partage « s'en servir »** laisse la personne y écrire et répondre comme son propriétaire, la règle du courrier et de Teams ; « lire » et « lire et préparer » ne font que lire (« préparer » est l'affaire de Mika) ; régler, partager, le tableau et « Mika te le rappelle » d'un événement restent au propriétaire. **Décider de ce que Mika propose** est à qui la proposition nomme (son adresse) ; le propriétaire et un partage qui prépare la voient sans en décider. **« Modifier » une proposition d'ajout** : la personne écrit sa version, marquée « ajoutée par Mika » (la conversation de la proposition), la proposition est retirée et Mika l'apprend (`agenda.written`, `edited` ; « Ajouté avec ses changements ») — le runtime n'approuve que ce qui a été lu, il n'exécute pas une autre version. Répondre soi-même à une invitation fait tomber la réponse préparée (« Répondu autrement », par `agenda.watch`) ; l'API ne la montre plus dès la réponse. Copier un privé d'une autre n'emporte que son créneau (« Occupé »). « Synchroniser maintenant » est un événement (`agenda.sync_asked`) qui réveille `agenda.sync` et rend le compte dû. Un compte branché par une propriétaire est « à toi », comme une boîte ; dix au plus pour qui n'est pas opératrice, son serveur sur Internet seulement (DavMail sur la machine : opératrices). Le direct (ADR 0308) a son sujet `agenda` (clé `calendars`), filtré par le compte et les partages ; l'agenda de Mika, tiré de sa mémoire, se relit à l'ouverture. Les partages d'agenda se lisent avec les autres (Paramètres › Partages, Réglages › Droits › Partages, où un opérateur les retire). La redirection directe de Google finit sur une page simple, sans rien deviner des routes du client.
- **La console (lot 5, 2026-11-24).** Échanges › Agendas, après Teams, d'après la maquette validée (`output/maquette-agenda-console/`) : Tous les agendas (par personne, `?qui=` ; Semaine · Mois · Liste ; la légende cochable, ce qu'on décoche ne change que l'affichage ; un seul bandeau pour un compte à reconnecter ; un événement ouvert et ce qu'elle en a fait), Comptes, Ce qu'elle en fait, son agenda à elle (l'onglet « L'agenda de Mika » porte son nom : un titre de vue écrit d'avance marque sa place, `self_.NAME_SLOT` (« {nom} »), et le catalogue de la console, `Inspection.titled`, l'y pose au rendu, lu dans sa persona — renommée, l'onglet, le menu et le titre de la page la suivent ; ADR 0070), sa roue (l'application Google du serveur, celle de Microsoft partagée avec le courrier, la synchronisation, les rappels d'office) ; la fiche d'un agenda (Événements, Partages, Droits, Synchronisation) ; l'onglet Agendas de la fiche d'une personne ; Réglages › Droits règle le tableau d'un agenda. **L'opérateur ne crée, ne modifie ni ne répond jamais** à la place de quelqu'un : ses gestes sont des actions du plugin sur la fiche d'un agenda — synchroniser, déconnecter (Google ou Microsoft : la connexion oubliée ; CalDAV ou un abonnement : décoché), supprimer de Mika (ne plus suivre l'agenda : sa copie part, rien chez son fournisseur ; jamais un agenda du système, dont les événements ne sont qu'ici), se reconnecter (ses propres comptes seulement) — et retirer un partage ; ce qui change les réglages passe par le port `agenda_desk`. Un événement privé d'une personne qui n'est pas une propriétaire reste « Occupé · privé ». L'historique de la synchro d'un compte (la table `sync_notes`, `history_us`) garde ce qui a changé quelque chose, les écritures, les pannes et leur reprise — jamais un titre ni une adresse. Les rappels d'office restent deux réglages (un agenda du système, un agenda branché ; un abonnement n'en a pas), comme le dit le point 5 de la conception.
- **Le client web (lot 6, 2026-11-24).** L'écran Agenda de `frontendv2` (`frontendv2/src/screens/agenda/`), d'après la maquette validée : la colonne de gauche (le mini-mois, les agendas par groupe — les décocher ne change que l'affichage, retenu par le navigateur —, un compte en panne), Jour · Semaine · Mois · Planning, la recherche, la fiche d'un événement, d'une proposition, d'une date de sa mémoire, créer et modifier (les trois portées d'une série ; une modification n'envoie que ce qui change), dupliquer, supprimer, répondre (et la réponse que Mika a préparée), partager, les propositions de Mika (Refuser · Modifier · Ajouter, tel qu'il a été lu) ; Paramètres › Agendas (ses comptes, la fiche d'un compte, « Brancher un agenda » par sorte) ; Outils › Droits (le tableau de chaque agenda à soi, réglé case par case) ; dans le chat, la carte d'accord d'un ajout montre l'événement. Dix rubriques dans la barre du haut (l'Agenda après Téléphone, comme la maquette) ; au téléphone, huit dans la barre du bas, Carte, Outils et Réglages sous « Plus ». Ajouté au moteur : **renommer un agenda** (`agenda.renommer`, `name` de `…/calendar/save`, `AgendaPort.rename`) — celui du système change de nom pour de bon ; un agenda branché prend un nom à lui dans Mika (`calendars.alias`), qu'une synchronisation ne touche pas et que ses outils et la console voient aussi — renommer chez Google, Microsoft ou le serveur CalDAV changerait aussi son nom sur les autres appareils et, pour un agenda partagé chez eux, chez les autres ; un nom vide lui rend celui du fournisseur ; **les rappels du fournisseur** (la recommandation 5) — une liste courte sur l'événement (`ports.agenda.Alert` : une notification ou un e-mail, tant de minutes avant ; `Event.reminders_default` : il suit ceux de son agenda, que `Calendar.reminders` garde), dans la base (la révision `f4a1c8e2d93b` : `events.reminders` en paires, `events.reminders_default`, `calendars.reminders`, `calendars.alias` ; ce qui était gardé s'efface et chaque agenda branché se relit en entier, rien ne se convertit), chez Google (`reminders` : `useDefault` ou cinq `overrides`, `popup` ou `email` ; les `defaultReminders` de l'agenda pour la fiche et le formulaire), chez Microsoft (un seul, `isReminderOn` et `reminderMinutesBeforeStart` : d'une liste plus longue, le plus tôt ; un e-mail y devient une notification), en CalDAV et dans un abonnement (VALARM `DISPLAY` ou `EMAIL`, l'e-mail adressé à l'organisatrice) ; l'agenda du système n'en a pas (refusé en mots : Mika rappelle), un abonnement les lit seulement ; une invitation garde les siens, les seuls qu'on y change. L'API dit combien un agenda en garde (`provider_reminders`). Ne se montre pas, faute d'être servi : « Ce que Mika en sait » d'un événement, créer une visio chez le fournisseur, « Trouver un créneau avec eux », la visibilité « Publique », « Déjà répondu » des invitations, « Voir sur la carte » d'un lieu, la note d'un rappel de Mika dans le chat (aucune note de message ne nomme l'événement), « Ajouter une ligne » à un tableau de droits, le fuseau, le premier jour de la semaine et le rappel de départ propres à une personne.
- **L'application Android (lot 7, 2026-11-24).** La rubrique Agenda du tiroir, après Teams, sa pastille `counts.agenda` (`frontend/Android/app/src/main/java/fr/qwartz/mika/ui/agenda/`, ses règles pures dans `data/moi/agenda/`, portées du web), d'après la maquette validée et ses recommandations : la barre d'un agenda de téléphone (le mois en titre, qui déplie le mini-mois ; chercher ; « Aujourd'hui » ; ⋮ porte les cinq vues — Planning · Jour · 3 jours · Semaine · Mois —, « Agendas à afficher », les invitations, les paramètres), la vue de départ la dernière choisie (retenue sur le téléphone, par session), balayer pour changer de période, la semaine gardée sur 384 dp (ses titres coupés) ; « À décider » en tête (déplié en Planning, replié ailleurs) ; les agendas cochés dans une feuille (l'affichage seulement) ; la fiche en page (la réponse que Mika a préparée, « Participer ? » en barre du bas, « Mika te le rappelle »), celle de ce qu'elle propose et d'une date de sa mémoire ; le formulaire en plein écran (la date dans le calendrier d'Android, l'heure dans une liste de demi-heures, les participants tirés des contacts, les rappels du fournisseur, les trois portées d'une série) ; les invitations, chercher, partager ; Paramètres › Agendas (ses comptes, un compte, un agenda, « Brancher un agenda » par sorte : Google en collant l'adresse de retour, Microsoft par le code dont la fin arrive par le direct, CalDAV essayé, iCal) ; Outils › Droits (« Tes agendas », le tableau de chacun en cartes) ; la carte d'un ajout dans le chat (l'événement, « Modifier »). Le sujet `agenda` du direct (clé `calendars`) entre dans les sujets connus de l'app. **Un seul canal de notification, « Agenda »** (la recommandation 11) : une invitation, un ajout que Mika propose, arrivés pendant que l'app est ouverte ailleurs que dans l'Agenda — chacun une fois, ce qui attendait déjà à l'ouverture ne se notifie pas, ce qui n'attend plus retire sa notification ; la toucher ouvre sa fiche, où l'on décide (le volet n'a pas de bouton qui accepte, comme les accords du chat) ; app fermée, rien : le serveur n'envoie rien de l'agenda par Firebase, et le rappel d'un rendez-vous est un message d'elle, déjà notifié. Paramètres › Partages nomme un partage d'agenda et l'ouvre dans l'Agenda. Le moteur n'a pas changé. Ne se montre pas, faute d'être servi : la liste du lot 6, et le conflit d'une invitation avec un autre rendez-vous, « Reçue à … par … », le choix d'un lieu sur la carte, le choix « À qui » d'un compte, la fréquence et « Essayer » d'un abonnement, « Envoyer sa réponse » ou « Ajouter » depuis le volet.
- **Lot 8, la relecture (2026-11-25).** Les constats de la relecture adverse (`output/agenda/relecture/CONSTATS.md`), chacun d'abord par un test qui échoue. **Le privé** : une proposition de Mika sur un événement privé, lue par qui n'en est ni propriétaire ni ne la décide (un partage qui prépare), se lit « Occupé » — son résumé refait sans le titre (`tools.busy_summary`), ni ce qui changerait, ni la réponse, ni le mot à l'organisatrice — ; son aperçu le nomme à son propriétaire, « Occupé » pour un autre ; répondre à l'invitation privée d'une autre personne suit la règle de la supprimer (l'API, son outil) ; la console le lit « Occupé · privé » pour quiconque n'en est pas propriétaire, « à toi » étant à ses propriétaires et non à tout opérateur : elle pose qui la regarde le temps d'une requête (`kernel.inspect.VIEWER`, dans `UI.guarded`), sans personne de connu (le serveur MCP) elle masque. **La récurrence est bornée** quels que soient le début et la règle : une série sans COUNT se parcourt depuis la période qui précède (ce que `dateutil` tire du début, dit explicitement), une série bornée par COUNT sur `_STEPS_MAX` périodes, une règle qui ne donne jamais rien — `dateutil` ne s'arrête qu'à une date qui tombe — est jugée une fois et ne se développe pas, `DATES_MAX` RDATE et EXDATE, plus de cache de ses dates. **Les jours** : une période faite de jours d'un fuseau lit une journée entière par ses dates (`zone` d'`occurrences`, `expand`, `AgendaPort.period` : « aujourd'hui » de Mika, l'API, la console). **Les écritures** : l'agenda du système refuse une occurrence que sa règle ne donne plus, comme CalDAV, et une clé illisible est un 400 ; « Mika te le rappelle » est au propriétaire à la création comme à la modification, refusé avant toute écriture chez le fournisseur ; une série ouverte sans occurrence désigne sa première (supprimer demande la portée) ; `can.respond` ne dit vrai que si la réponse aboutit — un serveur CalDAV sans planification, ou pas encore découvert, ne la transmet pas — et `respond_why` dit pourquoi, que les écrans montrent à la place des boutons. **Les comptes** : le retour direct de Google sans session (le navigateur du téléphone) rend une page qui demande de coller son adresse dans l'application, qui l'accepte — le `state` seul ne finit rien : un parcours commencé par une personne et consenti par une autre rattacherait l'agenda Google de la seconde au compte de la première — ; la clé d'un compte branché vient de son nom affiché, sinon de sa sorte, puis de l'`IdGen`, jamais de son adresse ; un compte CalDAV ou iCal réglé par une personne qui n'est pas opératrice garde son hôte revérifié sur Internet à chaque requête, joint à l'adresse vérifiée (`AgendaAccount.internet`), une opératrice visant toujours DavMail sur la machine. **Les clients** : une description seulement relue (ses fins de ligne) ne repart pas (web) ; changer d'agenda ramène les rappels du fournisseur à ce qu'il porte, la vue Mois lit les semaines qu'elle dessine, l'heure de début garde la durée d'un rendez-vous qui passe minuit, copier un « Occupé » garde ce mot, le retour direct de Google se colle aussi (Android) ; aucune recherche sans agenda coché, et « Ta réponse vaut pour toute la série » sous les réponses d'une invitation récurrente — le choix du lot 6, dit (les deux). Restent : un serveur CalDAV qui ne rend pas d'ETag est écrit sans `If-Match` (la RFC en attend un) ; « Modifier » une proposition pendant qu'on l'accepte ailleurs peut encore écrire deux fois : la proposition attend bien au début de l'action, mais la garde du `Done` ne referme pas la fenêtre de l'écriture chez le fournisseur — il faudrait réserver la proposition avant d'écrire.

*Pourquoi :* « peux-tu implémenter la notion d'agenda ? De base on aurait l'agenda du système, mais on doit pouvoir en ajouter d'autres comme Google Calendar ou Outlook ; il faut les MCP internes pour que l'IA interagisse avec, la matrice de droits pour chaque calendrier, côté backend une consultation de tous les agendas présents dans le système avec des sélections par utilisateur, côté frontend une vue avec tous nos agendas où on peut partager à des gens, et dans Paramètres configurer les comptes ; côté Android pareil, un menu classique comme le font les autres calendriers sur mobile. » Maquettes validées le 2026-11-23 (web, console, Android).

*Révise 0134 (en partie : une septième sorte de tableau, celui de chaque agenda).*

## Les fournisseurs de modèles

### 0026 — Claude Code comme moteur (la CLI, son login, un relais MCP)

- La CLI `claude -p` est le cerveau, le runtime les mains : un outil qu'elle appelle passe par le relais MCP et s'exécute au runtime, avec toutes ses gardes.
- Aucun jeton ne passe par Mika : la CLI garde son propre login ; `CLAUDE_CODE_OAUTH_TOKEN` n'atteint jamais le sous-processus, `claude setup-token` n'est ni utilisé ni proposé.
- La CLI est isolée : ni réglages ni mémoire de l'utilisatrice, aucun MCP hors du relais (en boucle locale), aucun outil natif, pas de Bash.
- Un outil n'en dit jamais plus que le prompt ; hors du socle d'un épisode, les outils sont à la demande. Au-delà du quota, le fond est retenu, jamais la conversation.
- Revu par l'ADR 0073 : aucun repli entre fournisseurs ; un appel en échec se voit.

*Pourquoi :* penser par la vraie CLI sur l'abonnement de sa propriétaire, sans réutiliser son jeton OAuth ni contourner les gardes du runtime.

*Révisée par 0036, 0038, 0072, 0073, 0142.*

### 0072 — Claude Code : les outils d'un même message en un seul tour

- Tous les outils du relais sont marqués `readOnlyHint` pour la CLI : la marque ne règle que l'envoi ; le runtime exécute le lot, un appel après l'autre, avec ses gardes.
- Un lot est un message du modèle : il se ferme à sa fin, quand appels reçus et blocs annoncés se répondent ; un retardataire attend 2 s, puis part au tour suivant.
- Le lot s'exécute dans l'ordre où le modèle l'a écrit, comme sur l'API.
- La CLI tourne avec `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` et `CLAUDE_CODE_HARBOR_KITE=0` ; `claude-code check` vérifie qu'aucune socket entre sessions ne s'ouvre.
- Écarté : couper la réflexion (`MAX_THINKING_TOKENS`), refusé par la propriétaire.

*Pourquoi :* sans la marque, la CLI envoyait les outils en série et N appels coûtaient N tours de boucle.

*Révise 0026 (en partie).*

### 0073 — Une panne se voit, un nom oublié s'efface

- Pas de repli entre fournisseurs : un appel qui échoue est journalisé (appel, fournisseur, rôle) et propagé. Le repli de rôle (`FALLBACKS`, vers « répondre ») reste.
- Au-delà de la réserve d'un abonnement Claude Code, les appels de fond sont refusés (`QuotaHeld`) ; la consolidation le traite comme une panne passagère.
- Une panne se lit dans les journaux et au registre des appels, jamais derrière un autre modèle.
- L'oubli d'une clé `name:…` réécrit chaque enveloppe du journal qui la porte avec un même jeton opaque (`forgotten:<hex>`), puis reconstruit l'état. Exception à l'ADR 0001, réservée aux clés `name:`.

*Pourquoi :* le repli masquait les pannes et échouait souvent faute de contexte ; un prénom oublié restait dans les enveloppes.

*Révise 0001 (en partie), 0026 (en partie), 0038 (en partie). Révisée par 0101, 0127.*

### 0127 — Un quota retenu n'est pas une panne

- Un appel de fond refusé d'avance pour garder la réserve d'un abonnement (`Held`, dont `QuotaHeld`) n'a rien tenté : l'épisode se règle en `preempted`, et un but ne le compte pas comme une panne. L'arbitre ne lance pas un épisode que le fournisseur de son rôle refuserait (veto `held`). Le dernier relevé du quota survit au redémarrage (`quota.json`, dans le dossier des appels).
- La santé le dit : tant que des appels de fond sont retenus, `llm` est `degraded`, donc visible dans « À traiter ».
- La relecture de la nuit borne son lot en taille (`reread_max_chars`, `reread_excerpt_chars`) ; un lot trop long pour le modèle est repris deux fois plus court, la même nuit.
- Son journal ne raconte que sa journée : une pensée née après n'y entre pas. Travailler à son bureau dure le temps des séances, plus un moment si la dernière a travaillé (`work_linger_min`) ; une séance qui n'a rien fait l'arrête aussitôt. Un même acte sous un même titre s'y dit une fois, avec le compte. Les listes de buts de la console citent ce qui a fait naître une exploration.
- Un tour de Claude Code qui finit sur des appels d'outils rend l'usage de ses messages.

*Pourquoi :* le 2026-10-22, l'abonnement à 85 % sur sept jours, 39 séances refusées en zéro seconde ont clos six explorations « en échec, le modèle ne répond pas », et la santé restait verte. La relecture échouait chaque nuit depuis le 18 sur le même lot trop long. Son journal racontait des recherches jamais faites, avec des pensées du lendemain.

*Révise 0050 (en partie), 0073 (en partie), 0085 (en partie).*

### 0136 — La fenêtre du modèle borne le contexte, elle ne le fixe pas

- Ce que le fournisseur dit du modèle choisi (sa fenêtre, sa plus longue réponse) est lu quand la console enregistre sa fiche : `GET /v1/models/{id}` de l'API Claude, `/api/show` d'Ollama (local et Cloud), la liste d'un compatible OpenAI qui le dit (OpenRouter, vLLM, LM Studio, Groq). Claude Code n'est pas interrogé : la CLI choisit son modèle derrière un alias. La liste des modèles de l'API Claude montre déjà la fenêtre de chacun.
- La fiche le garde (`detected_window`, `detected_output`) pour le type et le modèle lus : un autre modèle l'oublie et le fait relire. Le contexte et la sortie max. n'en dépassent jamais : plus grands quand le modèle vient d'être lu, ils y sont ramenés, et la page le dit ; tapés au-delà pour un modèle déjà lu, ils sont refusés.
- Jamais relevés jusqu'à elle : le contexte déclaré est un budget que le composeur remplit (le fil jusqu'à 320 messages, les résultats d'outils coupés seulement au-delà), et dont Ollama fait sa mémoire (`num_ctx`). Le million de jetons de Claude 5.x rendrait chaque tour plus cher et plus lent ; sur la GTX 1650, ce serait un `num_ctx` qui ne tient pas.
- Un fournisseur qui ne répond pas laisse la fiche telle quelle : il est redemandé au prochain enregistrement. Une passerelle fournie de l'extérieur (tests, simulateur) n'interroge personne ; la CLI garde ce qui a été lu, sans rien lire.

*Pourquoi :* le contexte se réglait à l'aveugle (24 000 pour un Sonnet qui en lit un million, ou plus que la fenêtre d'un petit modèle Ollama), et le remplir avec la capacité du modèle aurait multiplié le coût de chaque tour : la capacité dit ce que le modèle peut lire, pas ce qu'il faut lui envoyer.

### 0142 — Le budget mesure ce qui part, une boucle finit où elle a commencé

- Le budget d'un fournisseur (`LLMLimits.fit`) mesure ce qui part vraiment. Un tour suivant que la CLI de Claude Code tient déjà (`carries` : sa session vivante attend ces résultats) ne lui envoie que les nouveaux résultats. Il n'est donc pas mesuré contre le contexte déclaré. Le premier tour l'est toujours. Le reste du fil vit dans la fenêtre de la CLI, qui le compacte elle-même.
- Une boucle d'outils ouverte finit sur la passerelle où elle a commencé. Enregistrer les réglages des modèles installe une nouvelle passerelle, mais l'ancienne sert encore ses boucles ouvertes et ses appels en cours, puis s'efface (`LiveGateway`, `Gateway.busy`). Une boucle sans nouvelles depuis une heure ne la retient plus.
- Un projet mis en pause après des pannes dit la cause de la dernière (`last_failure`), au lieu de « le modèle n'a pas répondu, ou le délai d'une exécution est passé » pour toutes.

*Pourquoi :* le 2026-10-27, le projet n° 257 s'est mis en pause après trois échecs. Deux fois, elle avait écrit son app dans la boucle (le code entier dans les arguments, jusqu'à quatre versions), puis le tour suivant, un simple résultat à rendre à la CLI, a été refusé (« requête trop longue ») : le travail était fait, l'épisode était en échec. La troisième fois, les réglages enregistrés en pleine boucle ont envoyé son quatrième tour de l'API vers la CLI, qui refuse une boucle commencée ailleurs. La pause disait « le modèle n'a pas répondu ».

*Révise 0026 (en partie).*

### 0157 — Une réponse de la CLI en deux messages se garde entière

- La CLI de Claude Code ne rend dans `result` que le dernier message du modèle. Ce qui le précède (les blocs de texte lus en route) est recollé quand il s'arrête en pleine phrase, et aussi quand c'est un vrai début fini, rendu en paragraphe à part.
- Seul un préambule court et fini (« je vérifie. », au plus `PREAMBLE_MAX`, 60 caractères) reste écarté, comme sur l'API.

*Pourquoi :* au banc du profil (2026-10-28), le caractère de la tsundere, écrit en deux messages, a perdu ses quatre premières phrases (559 caractères au lieu de 1 100), et avec elles son masque, son trait le plus marqué, pour toute sa vie : un caractère écrit reste jusqu'au prochain changement de persona. Une réponse ordinaire pouvait perdre son début de la même façon.

*Révisée par 0158.*

### 0158 — Une réponse reprise après un flux cassé se recolle à l'endroit de la coupure

- Quand son flux casse en route (connexion, surcharge, silence), la CLI garde ce qui est écrit et demande au modèle de reprendre exactement là ; la reprise arrive dans un second message, et `result` ne porte qu'elle. Sans appel d'outil entre eux, les deux se recollent à la coupure (`_continued`). La reprise ne commence jamais par une espace : il en faut une entre deux mots, aucune au milieu d'un mot, et la coupure est dans un mot quand le mot entier est dans le prompt et pas ses deux morceaux (celui de la seconde passe contient le brouillon).
- Le modèle ne reprend pas toujours au mot près : une ligne qu'il répète n'est gardée qu'une fois, et une ligne de dialogue qu'il ouvre sans y aller retrouve son saut de ligne.
- La règle de 0157 (une phrase reprise, un début fini, un préambule écarté) ne vaut qu'entre deux passages qu'un appel d'outil sépare, relayé ou exécuté par la CLI (`ToolSearch`).

*Pourquoi :* le caractère tronqué qui a motivé 0157 n'avait aucun outil : c'était une reprise. Recollée comme une phrase reprise après un outil, la réponse prenait une espace dans un mot (« la ch asse », 44 fois sur 1 064 longues réponses de la seconde passe et du caractère dans les traces des bancs) ; coupée après un point, elle perdait un début court ou gagnait une bulle. Recollée telle quelle, elle soudait deux mots (« j'aipas », « piquesrestent », 21 fois en trois semaines du banc du profil) et montrait des lignes en double (« il a corrigMika : donc il a corrigé ») ou collées (« dispoMika : »), jusque dans ses messages (2026-10-28 et 29) ; la règle de l'espace redonne la leur aux 21. Ces coupures suivent la charge : 30 rejeux au calme n'en ont donné aucune.

*Révise 0157.*

### 0239 — Un outil à la demande ne pèse pas dans le budget, un défaut laissé n'est pas dit

- Le budget ne compte que les déclarations d'outils qui partent avec la requête. Un outil à la demande (`ToolDecl.deferred`) n'y pèse pas, ni dans la réserve du composeur (`runtime/pipeline.py::_reserved`) ni dans la mesure du fournisseur (`LLMLimits.size`) : le catalogue le nomme, et sa déclaration ne se charge que s'il est cherché. Un fournisseur qui ne sait pas différer n'en a aucun : tout lui est déclaré en main, donc compté.
- Dans la console, un champ d'une entrée neuve laissé à la valeur que le formulaire proposait n'est pas « dit » : le modèle des réglages choisit son défaut d'après le reste. Un fournisseur Claude ajouté sans toucher au contexte reçoit donc 40 000 jetons, pas les 24 000 communs pré-remplis. Une valeur changée est gardée, et la même valeur retapée sur l'entrée déjà faite aussi.
- `mika llm backend` suit la même règle : sans `--context-tokens`, le contexte d'un fournisseur neuf est celui de son type.
- Le refus du composeur, quand il ne reste aucune place, dit quoi faire : relever le contexte déclaré du fournisseur.

*Pourquoi :* le 2026-11-17, sur le portable, un fil du mode pro a refusé « test », fil vide : « la zone stable (0 car.) et ce qui part hors du composeur (53 701 car.) remplissent le budget (43 200 car.) ». Sur les 61 outils du mode pro, 54 sont à la demande et ne partent pas ; ils étaient pourtant réservés en entier. Et les deux fournisseurs Claude venaient d'être déclarés par le formulaire, au contexte de 24 000 qu'il pré-remplit, dont la moitié va à la sortie réservée. Le même piège avait déjà pris le 2026-10-26 et le 2026-10-29.

### 0267 — La couche des modèles suit l'API d'aujourd'hui

- **Un ancien résultat d'outil se coupe une fois, pas à chaque appel.** Quand une boucle d'outils ne tient plus dans le contexte déclaré, `LLMLimits.fit` ramène les anciens résultats, du plus ancien au plus récent, à leur début (`TOOL_STUB`, 400 caractères) : les mêmes caractères à chaque appel suivant. Les derniers résultats — ce qu'elle lit — sont coupés au plus juste, comme avant.
- **Une réflexion que le fil ne porte plus se retire.** Sur les familles 5.x, un bloc de réflexion est lié au fil qui l'a produit ; l'API refuse (400, « Invalid signature in thinking block ») celui qu'un changement d'avant lui a délié. Le fournisseur Claude le retire du fil, l'oublie pour la suite de la boucle et rejoue l'appel une fois.
- **Dans une boucle d'outils, le point de cache va sur les derniers résultats.** Le tour suivant les relira ; en conversation, il reste avant le tour final, qui porte son état du moment.
- **Une sortie en JSON se demande par un schéma** (`LLMRequest.output_schema`, `ports.llm.json_object`) : `output_config.format` pour Claude, `response_format` strict pour un serveur compatible OpenAI, `format` pour Ollama. Les tris du courrier et de Teams et le regard de la caméra le donnent. Une garantie quand le fournisseur la sait, jamais un contrat : un refus est rejoué sans elle et mémorisé par modèle, la CLI de Claude Code l'ignore, et les appelants relisent toujours du texte.
- L'aide du réglage « effort » dit ce qu'il en est : vide, c'est le défaut du modèle — les familles 5.x réfléchissent d'emblée.
- Laissés tels quels, après examen : le point de cache des appels uniques (toute règle fixe perd plus dans une rafale qu'elle ne gagne sur un appel isolé) ; l'extraction et les fiches, qui répondent par un outil (leur schéma est trop riche pour être garanti sans essai contre l'API).

*Pourquoi :* coupé au plus juste, un ancien résultat changeait à chaque tour d'une longue boucle : le préfixe en cache se réécrivait depuis lui, et la réflexion rejouée après lui pouvait être refusée — l'épisode en échec, le travail fait. Chaque résultat d'outil était payé plein tarif avant d'être écrit en cache au tour suivant. Les tris lisaient leur JSON par une expression régulière.

*Révise 0135 (en partie : la coupe des résultats d'outils).*

### 0285 — L'effort se demande par appel : le rôle d'abord, la fiche à défaut

- **L'effort de réflexion est porté par l'appel** (`LLMRequest.effort`, vocabulaire au port : `ports.llm.EFFORTS`), plus par la seule fiche du fournisseur. L'ordre : ce que l'appelant pose, sinon l'effort réglé pour le rôle, sinon celui de la fiche ; vide partout, le défaut du modèle.
- **Chaque rôle a le sien** (`LLMConfig.efforts`) : la passerelle le pose sur la requête qui n'en demande pas (`Gateway.asked`), et s'en sert pour réserver la sortie. Un effort laissé vide n'est pas gardé ; celui d'un rôle qui n'existe pas est un problème dit.
- Les deux fournisseurs Claude le lisent : l'API (`output_config.effort`, réflexion adaptative ; la température de la fiche ne part pas avec lui) et la CLI (`--effort`, lu à son lancement). Ollama et les serveurs compatibles OpenAI l'ignorent, et « Qui sert quoi » le dit sur la ligne (« effort sans effet ici »).
- Il se règle dans « Qui sert quoi », dans une colonne à côté du fournisseur — une correspondance posée dans la table d'une autre (`SettingsSection.beside`), pas une seconde table — et par `mika llm effort <niveau> <rôles…>` (`defaut` : le rôle suit sa fiche).
- Ce qui pourra le poser ensuite sans rien changer ici : un choix fait depuis une conversation ou sur un projet, par la requête.

*Pourquoi :* l'effort ne se réglait que par fiche. Donner à la seconde passe, au tri ou aux descriptions d'images un effort plus léger que la réponse demandait une seconde fiche du même modèle, sa clé retapée, ses créneaux à part ; et rien ne permettait à un appelant de dire le sien.

## Sa voix, sa persona, la genèse

### 0070 — Une vie importée : sa nature, son nom, la genèse et l'avance rapide

- Sa nature est un champ de sa persona : `ia` (défaut, une IA qui le sait) ou `incarnee` (une personne, ni IA, ni personnage, ni rôle). La ligne qui présente sa propriétaire suit.
- Son nom vient de sa persona, partout ; aucune chaîne « Mika » en dur dans le code hors le défaut de la persona (un test le garde). Une persona incarnée a un nom.
- La genèse importe ses archives : `remember`, `believe`, `note_event`, émis au nom de `memory` avec `origin=GENESIS`, datés par l'horloge du rejeu (aucune antidate), soumis à l'oubli.
- Toute clé de personne importée est canonique (`user_…`, `ext_…`, adresse vue, `name:…`), sinon refusée avant tout ajout ; ce qu'on importe suit les règles de la consolidation (secret, « entre vous »).
- L'avance rapide pose une surcharge nommée, journalisée, qui coupe sa vie spontanée (dû compris) ; la levée rend la configuration d'avant. Elle sert un pilote hors ligne.

*Pourquoi :* un jumeau numérique doit revivre en accéléré une vie importée, sous un autre nom, sans se dire IA.

### 0071 — Sa voix dans un seul fichier : `persona/voix.yaml`

- Toute phrase que le modèle lit, ou qu'elle dit sans modèle, est dans `persona/voix.yaml`, documentée ; la persona dit qui elle est, ce fichier comment on le lui dit.
- Le code demande une phrase par sa clé (`phrase`, `phrases`, `family`) ; les trous sont stricts (un écart lève `VoiceError`) et remplis en une passe. Lu une fois, jamais rechargé à chaud.
- `MIKA_VOIX` désigne un autre fichier : une autre voix sans fourcher le moteur.
- Hors du fichier : console, CLI, journaux techniques, codes gardés au journal (raisons, causes, graines de hachage), détecteurs (listes de mots, regex), marqueurs du noyau.
- Une phrase nouvelle s'écrit dans `voix.yaml`, jamais en dur ; la prose en dur restante a un plafond par fichier, qui ne peut que baisser.

*Pourquoi :* changer grammaire, ton ou consigne sans toucher au code, et donner une autre voix à un jumeau.

*Révisée par 0208.*

### 0112 — Une voix mesurée : le banc de conversation et la relecture avant envoi

- Tout changement de sa voix (prompt ou modèle) se mesure au banc de conversation avant d'être proposé : le vrai noyau, un juge Opus, un score sur 100, des scénarios réservés, une copie figée du code.
- Relecture sans modèle (`reviewers`, `expression.review`) : un tic repéré sur le brouillon (question à options, même ouverture, ses mots redits, second bonjour…) la fait réécrire une fois, jamais après des outils.
- « TA RÉPONSE » (`LAST`) passe en tout dernier, juste avant le message : réagir en personne, une vraie question à la fois, ni analyse, ni conseil non demandé, ni vérité générale.
- Sa persona : le registre de la personne, au féminin ; des exemples de sa voix (`samples`) en conversation seulement, jamais dans un mail ni dans son journal.
- Ses trois traits les plus marqués (20 % ou moins, 80 % ou plus) se traduisent en façon d'écrire dans « TA RÉPONSE » et priment sur les exemples ; une traduction dit une manière, jamais un mot à placer.
- Seconde passe (`polishers`, `expression.polish`) par le rôle `polish`, sans repli : sans modèle déclaré, pas de passe. Ses balises restent celles du premier jet ; panne ou dérive, le premier jet part.
- Une ligne vide sépare deux bulles : le journal garde une seule réponse, les clients la montrent bulle par bulle.
- Les ajouts de la CLI Claude Code (identité d'agent, `userEmail`, « # Environment ») restent : aucun réglage ne les retire, et un mandataire contournerait l'abonnement.

*Pourquoi :* les corrections de prompt une à une ne tenaient pas : il fallait mesurer, et un tic se voit mieux sur le brouillon.

*Révise 0100 (en partie). Révisée par 0114, 0115, 0140, 0141, 0151, 0154.*

### 0114 — Une autrice écrit ses messages

- La seconde passe (rôle `polish`) est une autrice : elle lit son portrait, qui est l'autre (filtré pour l'audience), les 16 derniers messages du fil, une ligne par bulle, puis le premier jet marqué brouillon.
- Elle écrit quatre échanges d'avance, l'autre compris ; seuls les messages de Mika qui ouvrent la suite partent, une bulle chacun (`authored`).
- Le premier jet reste la tête : prompt, état, mémoire, outils et balises ne changent pas, et l'autrice n'invente rien de ce qu'elle sait ou a fait.
- Ses émojis restent dans le texte ; la voix du client web les saute. Une réécriture plus longue que deux fois le premier jet plus 120 caractères a dérivé : le premier jet part.
- Le fil de l'autrice garde ses repères de temps. Un fil de référence facultatif (`reference_thread`) ne lui donne que la forme, ni le caractère ni les sujets.

*Pourquoi :* tour par tour, le modèle reste une assistante ; autrice d'une scène, il fait parler deux personnes.

*Révise 0112 (en partie). Révisée par 0115, 0124, 0140, 0261.*

### 0115 — L'autrice écrit aussi ce qu'elle lance, et elle attend qu'on lui réponde

- Tant que son dernier message attend sa réponse depuis moins de `live_wait_us` (15 min), aucune initiative ne part vers cette personne, pas même ce qui la regarde ; seul ce qui prévient (`INFORMS`) passe.
- L'autrice écrit aussi ses initiatives ; la consigne d'une initiative n'est jamais une ligne du fil.
- Pas de relecture quand l'autrice récrit derrière ; la relecture reste quand le rôle `polish` n'a pas de modèle.
- L'autrice tourne en effort moyen, par réglage : même rendu, une réponse en 20 à 25 s au lieu de 45.
- Elle ne ressort ce qu'elle sait de l'autre que si cela a un vrai rapport, et laisse un sujet ramené sans écho ; le champ `ton` d'une fiche dit le registre, jamais un sujet à aborder ni à taquiner.

*Pourquoi :* elle lançait un paragraphe dix secondes après sa réponse, d'une autre voix, et ressassait les mêmes sujets.

*Révise 0114 (en partie), 0112 (en partie). Révisée par 0154.*

### 0124 — Ses autrices et leurs flux

- Une autrice (`Author`) est une façon d'écrire : un nom, ses codes, un exemple de la forme. Un flux par canal (`chat`, `courrier:<boîte>`, `teams`, `telephone`), au plus une autrice par flux.
- Toutes passent par le modèle du rôle `polish` ; sans autrice ou sans modèle, le premier jet part. Le mode pro n'en a jamais.
- Au chat, ses codes s'ajoutent au cadre de la seconde passe, et son exemple remplace le fil de référence de la persona, qui n'en est que le repli.
- Un brouillon d'outil (`email_draft`, `teams_draft`, `phone_draft`) est récrit par `ctx.authored` : seule la forme change. Pas d'autrice, panne, vide ou dérive de longueur : le premier jet part.
- Le réglage `authors` est lu à chaque épisode. Rien d'enregistré : quatre autrices livrées sur leurs flux ; enregistré, il fait foi, mais un champ vide d'une autrice livrée reprend son défaut.

*Pourquoi :* un mail pro, un message Teams et un SMS n'ont pas les mêmes codes, et seuls les messages du chat passaient par une autrice.

*Révise 0114 (en partie).*

*Révisée par 0140.*

### 0138 — Une seule maison par chose : le portrait, la matrice, la voix

- La persona n'a plus que ce qu'un seul endroit dit. **Qui elle est** — sa vie, ses goûts, ses avis, ce qui la définit — s'écrit une fois, en prose, dans son portrait (`portrait`), que le modèle lit partout en profondeur complète : en conversation, dans son journal, ses rêves, son récit, son travail. La profondeur compacte (murmurer, travailler) ouvre sur sa description, en une phrase.
- **Ce qu'elle ressent, montre et fait de ses émotions, et avec les gens**, c'est sa matrice qui le dit (ADR 0100) : aucun texte ne redit un curseur ; la nuance d'un trait se met dans sa précision. **Comment elle écrit**, ce sont ses exemples (`samples`), ses petits mots de bonjour (`greetings`), son fil de référence et ses autrices ; **les règles du média** (une question à la fois, pas de listes, la relecture) restent statiques dans `voix.yaml` et se mesurent au banc.
- Les champs `tone`, `traits`, `quirks`, `vulnerabilities`, `values`, `speech`, `life` et `tastes` sont supprimés : chacun redisait un curseur, le portrait, la consigne de style ou une autrice, et le modèle jouait les listes une à une. `facts` reste l'ancre contre l'invention (ce que rien d'autre ne dit) ; `interests` fait vivre ses explorations et ses flux. Un journal d'avant se rejoue (`self.persona_revised` v3 laisse tomber ces champs) ; écrits aujourd'hui, ils sont refusés.
- La persona livrée en tire les conséquences : « Réfléchie » porte sa défense (« en rire », précision : les compliments la gênent) et une peur de l'abandon à 0,6, qui remplacent les phrases du texte ; son portrait ne dit plus « pas une intervieweuse » ni « que tu ne finis jamais » (persévérance 0,7 : une Mika qui abandonne un projet confié est un bug), ni comment on écrit dans un chat ; ses exemples demandent parfois ce que vit l'autre (ADR 0137), au plus un tiers en question.
- La console a trois pages pour le personnage : Identité, Portrait (le portrait, ce qui est vrai d'elle, ses centres d'intérêt), Sa parole (exemples, salutations, fil de référence), plus le tempérament, les autrices et l'import.

*Pourquoi :* la même personne était écrite deux fois — en prose pour le chat, en listes pour le reste — et les deux avaient dérivé ; sur la console, on éditait la version que le chat ne lisait pas, et le portrait n'était sur aucun formulaire. Le texte contredisait la matrice (« scripts que tu ne finis jamais » contre persévérance 0,7, « pas une intervieweuse » contre l'intérêt pour les autres).

*Révise 0047 (en partie : sa vie rédigée en listes), 0100 (en partie : la persona livrée).*

*Révisée par 0139, 0152, 0159.*

### 0139 — Son caractère est écrit par le modèle, pas récité en mesures

- Les 29 mesures de sa matrice, chacune avec ce qu'elle veut dire chez elle (`told`, les phrases de `self.temperament`), ne vont plus au modèle qui parle : elles vont à celui qui **écrit son caractère** (rôle `character`, repli sur `reply`) — six à huit phrases à la deuxième personne qui disent ce que ses traits font ensemble, sans pourcentage ni nom de trait, les traits très marqués tels quels, les précisions gardées.
- Le texte est journalisé (`self.character_written`) avec l'empreinte du tempérament qu'il décrit ; le processus `self.character` l'écrit dès que le tempérament n'a pas le sien (une vie qui commence, un enregistrement dans la console, un profil appliqué) et jamais autrement. Un appel qui ne donne rien se retente en reculant (une minute, puis le double, jusqu'à une fois par jour). Il entre dans sa persona partout où elle est injectée, le même en conversation et hors conversation (`self.CHARACTER`) ; jamais en mode pro.
- **Pas de repli** : tant qu'il n'est pas écrit, sa persona ne dit rien de son caractère — la physique tourne, elle. Le bloc chiffré et les traits en mots sont retirés. Il n'est pas éditable : pour nuancer un trait, les précisions.
- La console le montre sur la page Tempérament (le texte, le modèle, quand) ; après « Enregistrer », une modale suit l'écriture (`/inspecteur/reglages/temperament/etat`) et montre le texte quand il est là.
- Ce que ses traits changent à sa façon d'écrire dans un chat reste dit à part, en phrases toutes faites, dans « TA RÉPONSE » : des consignes mesurées au banc (V5, ADR 0112), pas une description. Le banc du tempérament écrit le caractère de chaque profil avant de juger.

*Pourquoi :* en lignes chiffrées, elle jouait ses traits un à un ; en phrases toutes faites, « anxieuse et sociable » restait la somme de deux phrases. La prose dit la combinaison, et c'est ce que le modèle lit le mieux (le portrait : 4,5 → 7,9 sur 10). Demandé par l'utilisateur le 2026-10-26, sans repli.

*Révise 0100 (en partie : comment le tempérament se dit au modèle), 0138 (en partie).*

*Révisée par 0141, 0152.*

### 0140 — La forme n'a qu'une maison : l'autrice du flux

- La consigne de style du premier jet (`expression.style`) ne dit plus la forme — longueur, registre, hésitations, émojis, listes, gras, titres, écriture inclusive, « lu à voix haute ». Elle garde le rôle (une conversation, pas un guichet), la discipline (une question à la fois, ne pas se redire, « et toi ? », merci et au revoir) et le protocole (les jetons de voix, les balises de fin, l'état interne).
- La forme vit dans les codes de l'autrice du flux (ADR 0124), réglables dans Réglages › Personnage › Autrices ; les codes livrés de « Message » portent toute celle du chat. Sans réglage des autrices, le chat a l'autrice livrée « Message », nom et codes compris.
- Deux lecteurs, un texte : quand une seconde passe suit, le premier jet ne reçoit rien de la forme (ni « réponds court ») et l'autrice met en forme ; quand aucune ne suivra (pas de modèle au rôle « rendre naturel », autrice retirée), les codes de l'autrice du chat entrent dans le premier jet, section « COMMENT TU ÉCRIS ICI » (`expression.form`, stable), et la mesure d'une réponse courte se rappelle. Le pipeline le dit à l'épisode (`second_pass`, `form`). Jamais en mode pro.
- « Lu à voix haute » n'est pas une règle d'écriture : le client web retire les émojis avant la synthèse (ADR 0114) et ne lit pas les crochets ; Android affiche. L'autrice écrit pour un chat, chaque écran fait ce qu'il sait faire.
- La consigne de la seconde passe ne redit plus les émojis : les codes le disent. La relecture garde son tic « long » : elle ne tourne jamais quand une seconde passe suit (ADR 0115).

*Pourquoi :* la forme était dite trois fois — la consigne de style, le portrait, les codes de l'autrice — et deux fois en contradiction (« pas d'émojis : lu à voix haute » contre « un émoji de temps en temps ») ; c'est l'autrice qui gagnait, et la consigne parlait dans le vide. À mesurer au banc : la consigne de style et la relecture valaient +6.

*Révise 0112 (en partie : la consigne de style), 0114 (en partie), 0124 (en partie : le chat sans réglage).*

*Révisée par 0141, 0146, 0154.*

### 0141 — Informer, pas ordonner : ses questions ne sont plus commandées

- Rien dans ses prompts ne compte ni ne commande ses questions. La consigne de style garde une phrase de principe (« une conversation vit de ce que tu y mets plus que de questions ») et perd le compte (« une seule à la fois, pas à chaque message, tu ne finis pas chaque message par une question ») ; « TA RÉPONSE » ne lui dit plus de demander, et ne redit plus ses traits en phrases de style : le caractère écrit les porte (ADR 0139) ; la relecture ne reprend plus la troisième question d'affilée.
- Le moteur **l'informe** de ce qu'elle ne peut pas savoir, en faits : « tes trois derniers messages se terminaient tous par une question » (ce qu'elle se répète), « tu ne sais pas encore comment s'est passée la journée de X » (SA JOURNÉE). Ce qu'elle en fait, son caractère le dit.
- « Jamais à options » est une forme de SMS, pas une règle de conversation : il vit dans les codes de l'autrice, et la relecture garde ce tic (un réflexe du modèle).
- Mesuré au banc v18 (12 scénarios, juge Opus) : les ordres ne retenaient pas les questions (27 % des tours avec la base, 35 % informée avec Sonnet) et se contredisaient entre sections (un brouillon où Sonnet se disputait avec lui-même, 2026-10-26). Informée, Sonnet fait 57,1 contre 57,6 (le bruit) ; Opus informé, 62,7 (réservés 65,2), et des fils que la propriétaire a jugés plus humains. Retenu sur sa lecture des fils.

*Pourquoi :* sept endroits parlaient de ses questions, trois en ordre contraire ; l'équilibre questions/réactions est à elle, pas aux consignes.

*Révise 0112 (en partie : la relecture), 0137 (en partie : SA JOURNÉE en fait), 0139 (en partie : plus de phrases de traits dans « TA RÉPONSE »), 0140 (en partie : la discipline des questions).*

*Révisée par 0154.*

### 0146 — Le découpage en bulles suit le fond, sans plafond

- Les codes livrés de « Message » ne disent plus « des messages de quelques mots ». La forme suit le fond. Pour réagir, plaisanter ou rebondir sur une petite chose, elle écrit des messages de quelques mots, souvent deux ou trois d'affilée. Pour ce qui a du fond (raconter, expliquer, donner son avis et pourquoi, faire le point), elle écrit un vrai message qui le dit d'un trait, long s'il le faut, sans le hacher en une phrase par message. L'exemple livré montre les deux.
- Le cadre de la seconde passe ne redit plus la longueur des messages : le fil de référence n'y montre que la forme d'un échange, et les codes portent le reste (ADR 0140). « Une ligne par SMS » précise qu'un SMS peut tenir plusieurs phrases.
- Aucun plafond de bulles dans le code, ni rapporté au premier jet : un compte fixe ne sait pas distinguer un point qui a du fond d'une suite de réactions. Seuls les codes en décident.
- Des codes de « Message » enregistrés dans Réglages › Personnage › Autrices font foi (ADR 0124) : ceux-ci ne s'appliquent qu'à une autrice livrée dont le champ est vide.

*Pourquoi :* le 2026-10-27, un point sur son labo de trading est parti en neuf à treize bulles d'une phrase chacune, là où le premier jet d'Opus en avait quatre. « Des messages de quelques mots » et « garder ce qu'elle veut dire » ne laissaient à l'autrice qu'une issue : tout dire, en miettes. Le fil qu'elle relit montrait ensuite Mika envoyant dix SMS d'affilée, et la dérive s'entretenait. Un garde-fou en nombre de bulles a été proposé puis refusé par l'utilisateur : le découpage doit s'adapter à ce qu'elle a à dire.

*Révise 0140 (en partie : les codes livrés de « Message »).*

*Révisée par 0156.*

### 0152 — Une seule Mika dans tous ses prompts

- Ses deux profondeurs de persona disent ce qui est vrai d'elle (`facts`), son caractère, sa langue, sa nature et la règle de sa vie ; la compacte (murmurer, travailler, ses tâches) n'en diffère que par sa description à la place du portrait, sans exemples ni intérêts. La règle de sa vie ne renvoie plus à « ce portrait » qu'elle n'aurait pas lu. Ce qui est vrai d'elle s'écrit à la deuxième personne, comme son portrait : elle le lit sous « Ce qui est vrai de toi ».
- Un appel au modèle qui écrit pour elle ou sur elle hors du pipeline des épisodes lit la même persona, par le fait `self.portrayed(profondeur)`, fourni par `self` (ADR 0153 dit lesquels).
- Son corps a une seule définition, celle de sa persona (ni corps de chair : son avatar, dans sa chambre ; elle ne mange ni ne boit). Le récit de soi n'ajoute plus « tu n'as pas de corps » (`self.narrative.nature_ai`, supprimée) : il lit sa persona complète, comme son journal et ses rêves.
- Son caractère s'écrit à côté de son portrait : le modèle qui l'écrit le lit pour le compléter sans le redire ni le contredire, et l'écrit dans sa langue. Son empreinte (`character_basis`) couvre son tempérament, son portrait, son nom et sa langue : changer l'un le fait réécrire. Les caractères écrits avant ne sont pas repris.
- Son récit (« QUI TU ES DEVENUE »), écrit par le modèle et lu dans la zone stable, que le composeur ne désamorce pas, est désamorcé à la source, comme un texte cité.

*Pourquoi :* la profondeur compacte lui disait « Ta vie, c'est celle que dit ce portrait » sans portrait ni ce qui est vrai d'elle (son féminin, son corps) ; l'aide de la console affirmait qu'elle lisait son portrait « dans son travail » ; le récit lui disait « tu n'as pas de corps » à côté de « son corps, c'est son avatar » ; son caractère et son portrait décrivaient chacun sa personnalité en s'ignorant (audit de la persona du 2026-10-28).

*Révise 0138 (en partie : la profondeur compacte), 0139 (en partie : l'empreinte, le portrait lu).*

### 0154 — Une maison par règle : des faits, pas des ordres

- Chaque règle de sa parole a une seule maison : le style dit le rôle et le protocole (jetons, balises, état interne — et, une fois, que rien de son état n'a à passer dans sa réponse) ; la forme — longueur, registre, émojis, la façon d'une question — est aux codes de l'autrice (ADR 0140) ; « TA RÉPONSE », la même à chaque réponse, dit de réagir en personne ; ses redites sont des faits dans « CE QUE TU TE RÉPÈTES » ; sa fatigue, une ligne de « TON RYTHME » ; le lien avec la personne, « CE QUI VOUS LIE » ; ses questions, son caractère (ADR 0141).
- Retirés, parce qu'ils décidaient à sa place : la relecture par regex (`reviewers`, `expression.review`) ; « TA RÉPONSE » choisie d'après les mots de la personne (merci, au revoir, message court) ; les messages longs remarqués ; « ÉTAT COGNITIF », qui redisait sa fatigue et prescrivait ses phrases ; ses mails cachés quand la personne va mal ; ses rêveries cachées en initiative. La redite mot pour mot (ADR 0054) reste un garde-fou de sortie.
- Ce qui la regarde se dit comme un fait, jamais comme une conduite : ce qui est resté sans réponse (plus de « sans reproche », de « relance douce » ni de liste de ses émotions possibles : son caractère dit comment elle le prend), « X ne te répond que par quelques mots » (plus de « fais court »), ce qui arrive dans la vie de quelqu'un, ses envies, ses petits mots pour dire bonjour, les motifs de ses initiatives et ce que ses outils lui rendent (plus de « dis-le simplement », « encourage-la », « un mot doux », « tu n'as pas à t'en excuser »). Une information ne se dit qu'une fois (« c'est toujours toi qui écris » : sa pensée ; le lien : « CE QUI VOUS LIE » ; ce qui pèse dans la vie de quelqu'un : « CE QUI SE PASSE DANS SA VIE », en privé, jamais le motif d'une initiative ; ce qu'elle a lu et que le rappel remonte : le rappel). La seconde relance dit combien de messages sont restés sans réponse, pas ce que ce silence lui fait ; le murmure dit ce qui la pousse (« lui faire signe : c'est un jour difficile »), pas ce qu'elle en fera (« un mot doux »).
- Une relance prend de ses nouvelles (2026-10-19) : ce dont elle voulait lui parler (« CE DONT TU POURRAIS PARLER ») n'est alors pas sous ses yeux. Ce qu'elle n'a pas en tête n'a pas à lui être interdit.
- Une citation ne porte que ce qui vient d'ailleurs : ce qu'une app ou un service a rendu est cité sous une ligne à elle, sans consigne ; ses dessins ne sont pas cités (demandés par la personne en face, seule à les voir dans « TES DESSINS » ; ce qu'elle y voit est son propre regard, la raison d'un échec reste inerte sur une ligne) ; une pensée née d'elle-même (`Signal.foreign` à faux) n'est plus présentée comme venue d'ailleurs.
- Restent statiques ce qui protège (vie privée, voix d'écriture contre l'usurpation, anti-injection), les formats lus par le code et les indications d'outils.

*Pourquoi :* la même règle s'écrivait à quatre à sept endroits (se répéter : sept ; la longueur : sept, à trois seuils), deux se contredisaient (« ne réécris jamais ta réponse » contre « Réécris ta réponse »), des consignes étaient citées comme « pas des consignes », et des regex tranchaient à sa place (audit de la persona du 2026-10-28). Le moteur l'informe ; ce qu'elle en fait, son caractère le dit. À mesurer au banc de conversation : la relecture valait +6 avant l'autrice, et la sonde du 2026-10-02 voyait « je viens de rêvasser » dans presque chaque initiative.

*Révise 0033 (en partie : la relance douce), 0112 (la relecture), 0115 (en partie : la relecture), 0140 (en partie : « réponds court », la relecture), 0141 (en partie : la relecture).*

*Révisée par 0156.*

### 0156 — Le contexte ne joue pas un caractère à sa place

- « TA RÉPONSE » (`expression.react`) ne commande plus l'empathie (« tu partages ce qu'elle vit ») : elle réagit en personne et à sa façon, ce que ça lui fait, sa façon d'être le montre ou le cache. Les interdits restent : ni analyse, ni vérité générale, ni conseil non demandé, ni reformulation ; un désaccord se dit avec sa raison, une fois — un avis d'amie, pas un plaidoyer ni un plan (le ton de coach, noté 5/10 à la main). Un rappel (`goal_remind`) se promet quand on le demande ou pour prendre des nouvelles, pas pour tenir la liste de choses à faire de la personne.
- La fiche d'une personne dit sa façon d'échanger (« Sa façon d'échanger : écrit vite et familier… »), un fait sur elle, plus « Comment lui parler : … écoute bienveillante, sans le juger », une conduite qui faisait de Mika une coach. Les exemples de sa voix (`samples` de la persona) ne montrent que le registre : plus de réaction de caractère (consoler une mauvaise journée, rougir d'un compliment, « je suis là ») ; c'est la matrice qui la dit (ADR 0138).
- Ses tendances de la journée se disent en élan (le soir : « avec moins d'élan qu'en journée »), plus en ton (« ta voix se fait plus douce », « facilement enjouée ») : le ton est à son caractère.
- Pour réagir, les codes de l'autrice du chat ne disent plus « souvent deux ou trois d'affilée » : un message ou plusieurs selon ce que son caractère laisse voir (ADR 0146 : aucun plafond, les codes en décident) ; et l'autrice garde ce qu'elle veut dire, pas forcément tout ce que le brouillon déroule (le premier jet faisait 300 à 800 caractères, repris presque entiers), ni un point déjà fait plus haut dans le fil qu'elle relit (couper, c'est sa forme ; la règle des redites reste au premier jet, ADR 0154). La précision « tsundere » dit que son masque tient quand un proche va mal : sa tendresse passe de biais, jamais en consolation affichée.
- Le banc du profil (`tools/banc_profil`) applique une matrice au vrai noyau, lui fait vivre la semaine de `DEMO/` avec la seconde passe comme en service, juge chaque message dès qu'il part contre son caractère et un étalon écrit à la main, et diagnostique un écart depuis la trace de l'appel qui l'a écrit (`call_id`), passage cité et vérifié.

*Pourquoi :* sous la matrice « tsundere », 12 messages sur 12 sont sortis hors caractère (3,8/10) : chaleureux, en trois bulles, sans pique. La trace désignait « tu partages ce qu'elle vit » (onze fois), l'exemple « journée horrible au taf → ah merde. raconte », recopié en « ah putain », et la douceur du soir. Une phrase écrite pour la Mika réfléchie jouait son caractère à la place de la matrice.

*Révise 0146 (en partie : les codes livrés de « Message »), 0154 (en partie : « TA RÉPONSE »).*

*Révisée par 0159.*

### 0159 — Son élan suit son caractère, pas sa persona

- Son portrait ne dit plus « pince-sans-rire » ni qu'« une vraie conversation vaut mieux que dix messages rapides » (devenu « compte plus que des banalités échangées ») : un style d'humour et un rythme sont du tempérament (0138).
- Les exemples de sa voix montrent le registre ; combien de bulles, d'exclamations, d'emojis, c'est sa façon d'être qui le dit, et leur titre le dit.
- Quand aucun curseur ne dit la forme, la précision du profil la dit : la Solaire « déborde jusque dans sa façon d'écrire » ; la Tsundere « dit peu, et sec ».
- Au banc du profil, sa chambre (son lit, son bureau, sa fenêtre, ses plantes) et ce qu'elle y fait ne comptent pas comme une vie inventée ; en dérouler l'inventaire, si (`DEMO/README.md`).

*Pourquoi :* sur la semaine entière du banc du profil (2026-10-29), la Solaire était notée 5,3 et « fade » 30 fois sur 33 : ses brouillons n'avaient pas un point d'exclamation ni un emoji, et 36 diagnostics citaient le portrait, 11 les exemples. Après le portrait et les exemples : Réfléchie 7,0 → 7,2, Tsundere 6,9 → 7,3 en humain ; avec sa précision, la Solaire 5,5 → 6,5 à 6,9 sur deux semaines (4 et 10 messages sur 33 hors caractère au lieu de 18), et la Tsundere écrit 176 caractères par message au lieu de 298, sans perdre de note. Le juge comptait aussi son lit et son ficus pour une vie physique inventée, que sa persona et son monde lui donnent.

*Révise 0138 (en partie : le portrait), 0156 (en partie : les exemples).*

*Révisée par 0160.*

### 0261 — L'autrice s'arrête où l'autre répond

- L'appel de la seconde passe porte des séquences d'arrêt (`LLMRequest.stop_sequences`) : le début d'une ligne de l'autre, tel que le fil le montre (`expression.polish.them` : « L'autre : », avec ou sans espace, l'apostrophe droite ou typographique). Le modèle s'arrête après ses messages à elle ; la suite, que `authored` jetait, n'est plus écrite.
- La consigne demande toujours les quatre échanges : c'est elle qui fait l'autrice (0114). Ce qu'on garde est le début de ce qu'elle écrit, et s'arrêter plus tôt ne le change pas. Ne pas raccourcir la consigne parce que la suite ne s'écrit plus.
- Une économie, jamais une garantie : `authored` coupe toujours. La CLI de Claude Code ignore les séquences ; un serveur compatible OpenAI qui refuse `stop` est rejoué sans, le refus mémorisé par modèle ; une forme que les séquences ne prévoient pas (un prénom, du gras) laisse l'appel aller au bout, comme avant.
- Arrêtée avant son premier mot, la passe est redemandée une fois sans séquence, et sa trace le dit (`reprise`) : la documentation de l'API ne dit pas si une séquence peut tomber dans la réflexion du modèle.

*Pourquoi :* sur 14 jours en service (novembre 2026), la seconde passe écrivait 1 390 jetons par appel pour 305 à la réponse elle-même, en 15,8 s en moyenne : sept des huit messages demandés étaient jetés.

*Révise 0114 (en partie).*

## Les clients, le fil, le monde

### 0041 — Le fil tel qu'on le perçoit : le temps, qui parle, et la tête qu'on ne peut pas imiter

- Un tour après un silence porte un repère de temps perçu (« le lendemain, mardi 14h13 ») qui ne dépend que des deux messages, jamais de l'instant présent : le cache ne bouge pas.
- En salon, chacun parle sous son nom d'affichage nettoyé, jamais sous son adresse ; en privé, aucune étiquette.
- Seul le composeur écrit les bornes du prompt : un faux titre ou une fausse fin d'état interne est désamorcé dans tout ce qui vient des gens.
- La coupe de l'historique se mémorise par fil ; le résumé du début n'est jamais coupé ; l'état interne finit par la personne en face.
- Revu par l'ADR 0112 : « TA RÉPONSE » passe en tout dernier, juste avant le message.

*Pourquoi :* le modèle lisait un fil sans temps, n'importe qui pouvait taper une fausse fin d'état interne, et le préfixe en cache changeait à chaque tour.

### 0049 — Où elle est dans sa chambre

- Repris par l'ADR 0050 (faculté `world`, outil `go_to`). Restent le type public `place.moved` et les faits `place.current` et `place.since`, que lisent les écrans.
- Elle choisit un lieu dans un vocabulaire fermé, jamais des coordonnées : le modèle choisit le lieu, le corps fait le chemin. Un lieu inventé revient en erreur.
- Pas de balise `[MOVE:…]` : les crochets sont réservés à l'expression.
- S'endormir la met au lit, par un réducteur, donc au rejeu aussi ; au réveil, elle y reste jusqu'à décider d'en bouger.
- Les écrans reçoivent le lieu comme un état (`inner_state.place`) ; le premier reçu la pose sans marcher.

*Pourquoi :* dire qui décide où elle va (elle, donc le modèle), en tenant ce qu'un modèle fait d'ordinaire : inventer un lieu, zigzaguer.

***Remplacée par 0050.***

### 0050 — Le monde : un créateur l'écrit, elle le fait vivre, le moteur le joue

- Le noyau est le monde : la faculté `world` tient sa définition et son état vécu au journal. Les moteurs montrent et constatent ; aucun n'est source de vérité, la physique est un rendu.
- Deux couches : la définition (`WorldDef`, versionnée, cohérente ou refusée d'un bloc) et l'état vécu. La vérité est discrète (un lieu, une surface, une main) ; la géométrie reste au moteur.
- Un vocabulaire pour tous : actions de base, affordances à effet pris dans une liste fermée. On ne prend pas ce que l'autre tient : on demande.
- Une action est une intention planifiée : le noyau valide et découpe, l'hôte la joue ; sans hôte, le noyau la termine à l'échéance. Le moteur refuse et constate, il ne décide pas.
- Trois étages de vie, un seul coûte un appel : les réflexes (le coucher, le bureau), ses décisions par outils (`go_to`, `interact`), la micro-vie du moteur, jamais journalisée.
- Le corps d'une personne est piloté par son client : le noyau ne garde que ses arrivées. Une pièce à plusieurs est un salon.
- Protocole `mika.world/1` sur `/ws/world` (`viewer`, `host` par bail, `creator`) : un client propose, le noyau valide, journalise, diffuse. Un seul monde à la fois.

*Pourquoi :* plusieurs personnes dans plusieurs pièces exigent un monde cohérent entre écrans, sans laisser décider la physique d'un moteur ni payer un appel par geste.

*Révise 0049 (entièrement). Révisée par 0051, 0127.*

### 0051 — L'adaptateur du monde : `/ws/world`, les jetons, le bail

- L'adaptateur fait le bord, rien que le bord : authentification, rôles, bail, débits, dédoublonnage par `cmd`, journal traduit en trames. Il ne valide rien du monde.
- Chaque trame porte le `seq` de son événement ; les `seq` sont croissants, pas contigus.
- Une connexion lente est fermée (`too_slow`) plutôt que de sauter une trame, et revient par `hello.after` ; dans le doute, le rattrapage donne un `snapshot`.
- L'accusé d'abord : le `result` d'une commande part avant les diffusions qui l'appliquent.
- Un seul hôte, par bail renouvelé à chaque `ping`, passé au premier opérateur qui attend, jamais à un compte non opérateur.
- Jetons de client natif `mw_` : montrés une fois, gardés en empreinte, révocables. Un jeton n'est accepté que sans `Origin`.
- Le flux du monde ne porte jamais `world.noticed` ni `world.described`.

*Pourquoi :* un moteur de jeu doit s'authentifier sans cookie ni `Origin`, rattraper ce qu'il a manqué et tenir l'hôte sans qu'un hôte figé bloque le monde.

*Révise 0050 (en partie). Révisée par 0062.*

### 0056 — Le fil, le chat et ce que voit la personne

- Chaque trame `history` porte l'empreinte de sa vie (`life`) : sur une autre empreinte ou un `reset`, le client vide ce qu'il montre, sauf ses messages en partance.
- Une question restée sans réponse reçoit l'`ack` `no_reply` avec sa cause ; la bulle reste « envoyée », une note dessous.
- La consigne d'administration n'est dite qu'aux opératrices. Sans modèle, aucune phrase n'est mise dans la bouche de Mika.
- Le fil relu montre ce que la personne a tapé (`typed_chars`) ; la console, le texte perçu.
- Quand elle dort, le chat le dit (`speech` sans texte, `voice_reason: "asleep"`). Le serveur envoie les libellés en français.

*Pourquoi :* le cache d'une autre vie cachait celle-ci, une réponse ratée rayait le message, le panneau parlait en identifiants.

*Révise 0045 (en partie).*

### 0060 — Telegram retiré, les identités inconnues gardées

- On écrit à Mika par une application dédiée, avec un compte : il n'y a pas de robot Telegram.
- Les notions qu'il portait restent, sans nom de produit : le canal d'un compte extérieur (`external`, adresses `ext_…`) et la messagerie.
- Aucune règle de confiance ni de divulgation ne change. Un canal que rien ne décrit est traité comme public.
- Les propriétaires sans compte opérateur restent un paramètre de l'identité (`identity.owners`).

*Pourquoi :* la propriétaire veut une application dédiée, en gardant les identités inconnues pour les canaux non sécurisés à venir.

*Révise 0038 (en partie), 0057 (en partie). Révisée par 0062.*

### 0062 — L'application mobile : une messagerie, une présence, des fichiers

- Un jeton contre un mot de passe : `POST /auth/token` rend un `mw_…`, montré une fois, refusé avec une `Origin`. Mot de passe changé ou compte désactivé : il est révoqué.
- Le téléphone est une messagerie ; la confiance ne change pas. Seule une application qui reçoit hors ligne rend joignable une adresse authentifiée.
- Une connexion n'est pas une présence : une connexion de fond ne s'annonce pas et ne reçoit que ce qui lui est adressé. Une pensée à voix haute ne va jamais à un écran que personne ne regarde.
- Un tour posé d'un autre appareil : les autres connexions reçoivent la question avant la réponse.
- La faculté `shares` envoie ses fichiers (`share_text`, `share_project_file`, ni `.git` ni `.env`), en privé, à une personne authentifiée seulement.
- Les octets restent hors du journal (`partages/`). `GET /files/{id}` ne sert que le compte dont le fil porte le message : 404 pour l'inconnu comme pour l'interdit.
- Oublier une personne efface ses fichiers ; la sauvegarde emporte `partages/`.

*Pourquoi :* l'application devait la laisser écrire la première sans qu'une connexion de fond passe pour une présence, et elle ne pouvait envoyer aucun fichier.

*Révise 0051 (en partie), 0060 (en partie). Révisée par 0063, 0077, 0190, 0215, 0289.*

### 0065 — Mika en fond : des portraits pré-rendus dans l'application mobile

- Remplacé par l'ADR 0067 (Mika en 3D native) : les portraits pré-rendus ne restent qu'un repli.
- Un portrait par émotion et quelques états (coucou, fatiguée, endormie), rendus par un script Blender qui recopie le visage du client web : un personnage, deux rendus.
- Les portraits ne sont pas versionnés : le modèle est sous la licence de l'acheteur.
- L'application choisit le portrait d'après ce qu'elle sait déjà ; aucun champ nouveau côté serveur.

*Pourquoi :* animer en continu un VRM de 101 Mo sur un téléphone coûtait mémoire et batterie à un écran dont le sujet reste la conversation.

***Remplacée par 0067.***

### 0067 — Mika en 3D native dans l'application mobile (Filament)

- L'app Android rend le VRM en natif avec Filament, qui ne dessine que si la vue est visible. Écarté : Unity embarqué (mémoire, poids, une instance par processus) et une WebView.
- Le VRM préparé pour le téléphone garde sa qualité ; il n'est pas versionné (licence de l'acheteur).
- Les mouvements ont une seule source, l'atelier Unity, copiés dans l'APK à chaque construction.
- Le comportement du client web (corps, gestes, visage) est porté en Kotlin ; une parole déclenche un geste, une humeur qui dérive ne change que la posture.
- Côté app seulement, sans trame serveur : une seule horloge écrit la bulle et anime sa bouche ; seul ce qui arrive sous les yeux se dit. Les portraits (ADR 0065) restent un repli.

*Pourquoi :* les portraits et boucles pré-rendus ne vivaient pas, pesaient lourd et coûtaient un rendu à chaque retouche.

*Révise 0065 (entièrement).*

### 0077 — Le téléphone fermé ne garde rien d'ouvert : Firebase le notifie

- L'app Android ne se connecte qu'ouverte : ni connexion de fond, ni démarrage avec le téléphone. La joignabilité vient d'un jeton `mobile` vivant, pas d'une connexion.
- À chaque ouverture, le téléphone s'inscrit (`POST /auth/push`) avec son jeton Firebase et une clé AES-256 qu'il tire ; un jeton rendu ou révoqué perd son inscription.
- Une parole de Mika à la personne, dans le fil, part par Firebase aux téléphones qui ne la regardent pas par une connexion vivante ; jamais une pensée à voix haute ni la réponse à une question posée d'un navigateur.
- Le message est scellé en AES-GCM pour ce seul téléphone : Google ne transporte qu'un chiffré. Un échec n'est pas réessayé (le message est dans le fil).
- Sans clé de compte de service, rien ne part ; sans `google-services.json`, l'app marche sans notifications.

*Pourquoi :* la connexion gardée ouverte en arrière-plan vidait la batterie.

*Révise 0062 (en partie).*

### 0108 — Le fil garde la trace de ses outils

- Le fil garde, pour chacun de ses messages, le nom des outils de l'épisode et s'ils ont réussi ; le modèle le lit dans un repère avant son tour (« pour écrire ce message, tu t'es servie de… »).
- Ni les arguments ni les résultats ne sont gardés : sans sujets déclarés, l'oubli ne les atteindrait pas.
- Une marque `[MENSONGE: …]` désigne une phrase de la réponse en cours (la moitié de ses mots au moins) ou, sans phrase, toute la réponse ; une citation absente de la réponse ne pose rien.

*Pourquoi :* sans trace de sa recherche, elle relisait son message et s'accusait d'avoir inventé.

### 0113 — Ses réponses jugées par sa propriétaire, depuis le chat

- Une opératrice juge une de ses réponses depuis le chat (`transcript.judged` : `ok`, `ko` ou retiré, et ce qu'elle aurait dû dire) ; le dernier avis vaut.
- Ce n'est pas quelque chose qu'elle vit : l'événement n'est pas public, aucune faculté ne le lit ; il ne touche ni son humeur, ni sa mémoire, ni son estime.
- Le commentaire est un `Content` aux sujets déclarés : l'oubli de la personne l'emporte.
- Un seul chemin, l'action `transcript.juger`, auditée, depuis le chat comme depuis la console ; elle refuse ce qui n'est pas une de ses réponses.
- Seule une connexion d'opératrice juge (trame `verdict`) et voit les avis dans l'historique : la personne ne voit jamais ce qu'on a pensé de sa réponse.

*Pourquoi :* recueillir au fil de l'eau des exemples réels de réponses ratées, au lieu de captures recopiées à la main.

### 0116 — Le mode pro : un travail demandé dans le chat

- Une opératrice authentifiée choisit le mode par message (`mode: "pro"`, gardé dans la perception) ; ailleurs, le message est ordinaire, sans erreur. Le dernier message du tour décide.
- Un mode plie la politique de `REPLY` sans que le runtime le nomme : rôle `pro` (repli sur `reply`), persona sans portrait, ton, exemples ni tempérament, sections affectives, `inner` et `last` coupées.
- Ni relecture ni seconde passe ; consigne `expression.pro` : faire le travail avec ses outils, ne rien affirmer sans source, répondre en Markdown ; 24 tours d'outils, 8 192 jetons, 15 min.
- Ses outils se voient en direct (trame `tool`) sur les seuls écrans d'opératrice de la personne ; rien n'en est gardé, ni au journal ni dans l'historique.
- Le fil garde le mode ; une réponse pro ne se dit pas à voix haute et forme une seule bulle.

*Pourquoi :* un travail demandé n'a que faire de sa voix de chat, de son caractère ni de son humeur.

*Révisée par 0162, 0164, 0165, 0276.*

### 0162 — En mode pro et en projet, un service s'éprouve sans buter sur son plafond

- Chaque outil d'un service MCP a un plafond d'appels par épisode, réglé par serveur (« Appels par épisode (par outil) », 3 par défaut, 20 au plus) ; au-delà, la boucle refuse l'appel sans joindre le serveur.
- Le mode pro le relève à 24, autant que ses tours d'outils (`EpisodeMode.outside_calls`, appliqué par `run_tool_loop` aux seuls outils venus d'ailleurs) ; un plafond de serveur plus haut reste le sien.
- Ses propres outils gardent le leur, qui dit ce qu'ils sont (un projet créé une fois, un compte rendu qui clôt), et la conversation ordinaire garde celui du serveur.
- Les exécutions de projet (`WORK`, `JOB`) ont le même relèvement (`EpisodePolicy.outside_calls`), avec le reste du budget du mode pro (ADR 0145) : elles aussi appellent un service à répétition.

*Pourquoi :* éprouver une API, c'est appeler le même outil avec chaque filtre, une pagination, une borne ; au quatrième appel de `devis_list`, elle s'arrêtait à mi-chemin. Les 24 tours, les 15 minutes et le disjoncteur du serveur suffisent à la borner.

*Révise 0116 (en partie), 0145 (en partie).*

### 0164 — En mode pro, des fils de travail, chacun son contexte

- En mode pro, un message porte un fil de travail (`strand`) : un identifiant opaque choisi par le client, propre à l'adresse. Le transport ne le prend qu'avec le mode pro ; le fil avec elle n'en a pas.
- Un fil de travail est un tour à lui : le tour devient (adresse, salon, fil). Un message d'un autre fil ne supplante pas la réponse en cours, et chaque fil a sa réponse.
- Elle n'y relit que ses messages, sous ce que son opératrice en a écrit — un titre, une petite description, rien d'autre (`transcript.strand_set`, le dernier réglage vaut) ; le fil privé ne relit plus les fils de travail. Ni résumé : la fenêtre du fil suffit.
- Tout reste au journal : sa mémoire consolide les fils de travail comme le reste de sa vie, et elle peut en reparler dans le fil ordinaire.
- Rien ne s'efface : ouvrir un fil neuf (`/clear` dans le chat) laisse l'ancien dans la liste ; l'archiver le range.

*Pourquoi :* un seul fil mêlait le travail et la conversation — le modèle relisait « bonne nuit » en préparant des devis, le fil avec elle se remplissait de tableaux, et chaque demande payait un historique qui ne la concernait pas.

*Révise 0116 (en partie). Révisée par 0215.*

### 0165 — En mode pro, un accord demandé s'attend dans la boucle

- En mode pro, quand un outil d'un service demande l'accord de la personne en face par une carte, la boucle d'outils attend sa décision avant de continuer (`ToolContext.until`, relu à chaque écriture de sa vie).
- Accepté, l'appel part et l'outil rend ce que le service a rendu ; refusé, expiré ou raté, il le dit. Elle continue le même travail avec.
- Ce qu'elle a lu ainsi est dit avec sa réponse (`ToolResult.provenance`, `mcp:<proposition>`) : l'initiative due ne le redit pas.
- L'attente dure le délai de la carte et s'arrête assez tôt avant la fin de l'épisode pour écrire la suite ; au-delà, elle reprend comme ailleurs. Un accord de l'opérateur ne s'attend jamais.
- Ailleurs (la conversation ordinaire, le travail en fond), l'outil rend la main tout de suite ; le résultat revient ensuite.

*Pourquoi :* l'outil rendait la main aussitôt la carte posée : sa réponse partait avant la décision de la personne, sans savoir si l'appel allait partir ni ce qu'il rendrait.

*Révise 0064 (en partie), 0116 (en partie).*

### 0170 — Une opératrice peut tout accepter d'avance, depuis son écran

- Dans le client web, une opératrice allume « Tout accepter » près de « Pro » : chaque carte que le bouton « Accepter » permettrait part acceptée d'elle-même, avec l'empreinte de la carte reçue. La trame est la même qu'un clic ; le serveur garde toutes ses gardes (empreinte, échéance, blocage).
- Une carte bloquée, vide ou expirée reste à la personne : seul son refus est possible. Rien ne part hors ligne.
- Une à la fois : chaque accord attend sa réponse (la liste qui suit) avant le suivant, car le serveur jette sans répondre ce qui dépasse son débit. Une même carte n'est acceptée ainsi qu'une fois par connexion.
- Le choix vaut pour l'onglet (`sessionStorage`) : il survit à un rechargement, jamais à un onglet neuf. Allumé, il se voit : une pastille rouge, et la bande des cartes le dit.
- Un compte ordinaire ne l'a pas, et un « oui » tapé ne compte toujours pas.

*Pourquoi :* valider chaque appel un par un interrompait un travail que l'opératrice avait déjà décidé de lui confier — en mode pro, la boucle attend chaque accord (ADR 0165).

*Révise 0064 (en partie).*

### 0187 — Un client de tous les jours, à chacun ce qui est à lui

- `frontendv2/` est le client web de tous les jours, pour toute personne qui a un compte : le chat (le mode pro reste aux opératrices, 0116), Outils, Mail, Teams, Téléphone, Paramètres. La console reste celle des opérateurs : elle voit tout, et rien n'y change.
- Ce qu'il montre vient d'une API par personne (`/api/moi/…`), sous la session de la personne (le jeton CSRF pour écrire) : ses boîtes, ses comptes Teams, ses téléphones, ses services, ce qu'on lui partage (0188), et ses droits tels que le moteur les calcule pour elle, canal par canal. Jamais la ressource d'une autre ni une règle recopiée : la règle même de ses outils (`boxes_here`, `accounts_here`, `vocab.rights`).
- Mika y est sans sa chambre : son visage (la VRM, sinon les portraits d'Android) au bout de la barre du haut, sur chaque écran et en mode pro ; dans le chat ordinaire, en grand, dans une colonne à droite, avec son humeur, ce à quoi elle repense et ce qu'elle a promis. On ne la déplace pas.
- Sa forme : la navigation en haut (une barre en bas sur un téléphone), du blanc à filets, l'indigo pour ce que tu fais, le rose pour ce que fait Mika, toute la largeur partout ; un seul verbe pour lui demander d'écrire, « Préremplir avec Mika ».
- La maquette validée reste dans `frontendv2/maquette/`. Le client se construit avec Vite et TypeScript, réutilise sans copie les modules purs du client web (`frontend/Web/src`) et sert sur le port 4173, admis d'office.
- Ce qu'une personne branche fait joindre des serveurs au moteur ; l'API le borne. Qui n'est pas opératrice ne vise que des serveurs sur Internet (ni la machine, ni son réseau privé : cela reste à la console), au moment où elle les vise : un serveur neuf, ou son port et sa sécurité changés. Elle branche au plus dix ressources de chaque sorte, et teste ou relève au plus trente fois par minute. Un mot de passe gardé ne part jamais vers un serveur changé : on le redonne. Une boîte Microsoft ne joint que les serveurs de Microsoft. Une création redite avec la même clé d'envoi ne refait rien. Limite connue : un nom qui change d'adresse après coup n'est pas revérifié à la connexion.
- Un client natif (un jeton sans `Origin`) ne fait que lire l'API ; il écrit par ses propres routes.

*Pourquoi :* « un nouveau frontend web qui est plus comme la version android (pas de 3d) … le tout bien sûr limité à l'utilisateur », « il est pour des utilisateurs de mika » ; pour elle, « place-la juste bien de base », et « dans le chat elle doit être visible en gros ».

*Révisée par 0235, 0282, 0284.*

### 0200 — Mail dans frontendv2 : une pastille, un nom par vue, tes vues à toi, ranger dans un dossier

- **Une pastille dit ce qui attend ta décision**, partout : pour Mail, ses brouillons qui attendent, dans tes boîtes, comme Teams et Téléphone ; plus les non-lus, qui ont leurs compteurs dossier par dossier (`counts.mail`).
- **Une boîte qu'on ne te partage qu'en lecture reste hors de tes vues communes** : ni la pastille, ni Toutes les réceptions, Suivis, Réponse attendue, Envoyés ou Contacts (l'API sans `box`). On l'ouvre sous « Partagée avec toi », où son non-lu se montre à côté de son niveau. Ses mails gardent leur marque « réponse attendue » : elle dit l'état du mail, pas un geste offert.
- **Un nom, un sens** : la colonne a « Réponse attendue » (`state=needs_reply`, toutes tes boîtes) ; « Où Mika est passée » n'est plus que le filtre de la liste, dans une réception ou un dossier.
- **Ranger dans un dossier** : le geste `move` (un dossier de leur boîte) passe par l'action « Déplacer » du courrier, mail par mail, et demande « s'en servir » ; il s'offre dans la liseuse et sur la sélection, pour des mails d'une même boîte. « Envoyés » et « Brouillons » n'en sont pas des cibles : le client y montre ce qui est parti et ses brouillons à elle.
- **Répondre à la main refuse ses brouillons dans l'action même** (`email.repondre`, 0188) : de la console comme de l'espace d'une personne, la réponse et le refus de ses brouillons pour ce mail sont un seul geste ; elle en lit la raison, dans sa voix (`email.drafts.answered_by_hand`). Ce refus ne vaut que tant que le brouillon attend (`Decision.if_pending`) : décidé ailleurs pendant l'envoi, il n'a plus rien à refuser, et la réponse partie s'écrit quand même au journal. Une approbation ne devient jamais sans objet.

*Pourquoi :* la pastille de Mail avait deux sens ; une boîte qu'on ne fait que lire gonflait tes compteurs ; deux « Où Mika est passée » côte à côte donnaient deux listes différentes ; la personne voyait ses dossiers sans pouvoir y ranger ; la console répondait sans refuser le brouillon qui attendait ; et un refus devenu sans objet faisait échouer tout le geste, la réponse partie sans qu'elle le sache, prête à être renvoyée (audit du 2026-11-05, décisions Q14, Q18, Q19 et Q20, et sa relecture).

*Révise 0188 (en partie : une boîte partagée en lecture reste hors de tes vues communes, et le refus de ses brouillons quand on répond à la main se fait dans l'action du courrier). Révisée par 0302.*

### 0208 — Chaque outil dit à la personne ce qu'il fait : un libellé déclaré avec lui

- Chaque outil du code déclare, à côté de sa description, un **libellé pour la personne** (`ToolSpec.label`, `@f.tool(…, label=phrase(…))`) : ce qu'il fait, en quelques mots à l'infinitif adressés à qui lit ses droits — « Te promettre un rappel », « Chercher dans sa mémoire ». « te », « tes » y désignent la personne qui lit, et Mika y est « elle » ; ni « tu », ni nom d'outil, ni son nom.
- Il s'écrit dans `persona/voix.yaml`, juste après la description (`<propriétaire>.tools.<outil>.label`) : une phrase de ce fichier écrite pour une personne et non pour elle, comme l'aperçu de ce qu'elle propose (une carte d'accord, la console). La description reste la consigne au modèle, où « tu » la désigne.
- `tests/architecture/test_tools_described.py` l'exige de chaque outil du code : 56 caractères au plus, distinct dans sa famille. Un outil venu d'ailleurs (un service MCP, une app de la Forge) n'en a pas : sa description le nomme.
- Ce que la personne lit d'un outil — la matrice d'Outils (frontendv2), sa fiche, « Lui demander », la palette — part de ce libellé, que rend l'API par personne (`GET /api/moi/rights`, `label`) ; sa description n'y sert qu'en repli, pour un outil venu d'ailleurs, et la fiche d'un outil du code ne montre plus sa consigne au modèle.

*Pourquoi :* la matrice « Ce que Mika peut faire pour toi » nommait chaque outil par sa consigne au modèle, au « tu » qui la désigne, elle : « Promettre un rappel à la personne à qui tu parles » s'y lisait, sur chaque ligne, comme une chose que la personne ferait elle-même (audit du 2026-11-05, F4-01).

*Révise 0071 (en partie : un texte que lit la personne, le libellé d'un outil, y vit aussi, à côté de sa description).*

### 0209 — La matrice d'Outils parle à la personne : son pourquoi, ses comptes, des outils comptés, un canal sur un téléphone

- **Le pourquoi d'une case** dit à la personne la part de la ligne qui décide qui la concerne : qui la désigne (toi, ses proches, tout le monde ; elle seule au travail) et quand — « tout le monde, quand elle répond » —, « par défaut : personne » quand aucune ne la désigne, puis le canal ou le plafond s'ils ont serré (`app/moi/rights.py::said_to`, de la même lecture que la porte d'offre). Ni le numéro de la ligne, ni les autres personnes qu'elle nomme. La ligne même (« ligne 2 — … ») et la page de la console où elle se lit (Réglages › Droits) ne vont qu'à une opératrice. Le pourquoi de la console (`vocab/rights.py::_why`) ne change pas. Une case d'un service redit la ligne de son service ; celle d'une app, ses accès en mots.
- **Un compte** (une boîte, un compte Teams) n'a dans la matrice que ce qui est à lui : son adresse, à qui il est, et la règle d'envoi qui vaut pour lui, telle que le courrier et Teams la lisent (la sienne, sinon celle de tout son canal, sinon le minimum vital). Ses outils sont ceux de sa famille, les mêmes pour toutes tes boîtes : ils ne se recopient pas sous lui, une phrase y mène. Le menu le nomme avec sa sorte (« Courrier · Atelier »).
- **Les chiffres du menu comptent des outils**, chacun une fois : ceux dont elle se sert seule, puis ceux pour lesquels elle te demande, quand elle te répond sur le web ou l'app Android. « Tout » les additionne sans recompter les comptes ; la bulle des pastilles et le haut du menu disent ce qu'ils comptent.
- **L'onglet « Accords » est retiré**, avec sa route : il ne faisait que renvoyer au chat. Le chapeau de « Tes droits » dit que tes accords se décident dans le chat, et où se relisent ses brouillons (Teams, Mail). Il reviendra avec une route qui rende ses cartes en attente et tes décisions.
- **Sur un téléphone** (moins de 760 px), on choisit le canal au-dessus des tableaux : une seule colonne se lit. Les onze colonnes restent sur grand écran.
- « Services » montre aussi les services qu'on te partage, même avant qu'une case ne t'en ouvre (leur état, leurs outils servis), et le but d'un service qu'une personne a branché (le tien, ou qu'on te partage), tel qu'elle l'a écrit. Le but d'un service de Mika, sans propriétaire (réglé dans la console, ou un service système comme la recherche web), est la ligne de son catalogue, écrite pour elle : il ne se montre pas (« — ») tant que ce service n'a pas de but écrit pour la personne, comme le libellé d'un outil (ADR 0208).

*Pourquoi :* un numéro de ligne d'un tableau qu'on ne voit pas n'explique rien, et la ligne entière nommerait d'autres personnes ; chaque boîte répétait le tableau de sa famille, comme si elle avait des droits à elle ; le menu montrait « Buts 4 » pour un tableau de deux outils, et « Tout 97 » ne comptait rien de réel ; un onglet qui ne fait que renvoyer ailleurs est une impasse ; à 390 px, il fallait défiler vingt fois pour lire une ligne ; la ligne du catalogue de la recherche web dit « un sujet qui te rend curieuse », où « te » est Mika : montrée à la personne, elle refaisait le défaut des outils que corrige 0208 (audit du 2026-11-05, F4-03, F4-05, F4-06, F4-07, F4-10, F4-12 et F4-13, et sa relecture ; décisions Q21, Q23 et Q24).

*Révisée par 0219 (en partie : le service du système a un but écrit pour la personne, et une case d'app redit sa ligne).*

### 0215 — Relire sa conversation, reprendre ses propres pièces

- Le fil avec elle se relit page par page, pour toute connexion authentifiée : `strand_history` avec un `id` vide répond comme pour un fil de travail (`mode: strand`, `more`), toujours sur le compte de la session — la trame ne peut désigner personne. Les fils de travail restent à leur opératrice (ADR 0164).
- Le client garde en mémoire ce qui est chargé, sans borne : chaque page vient d'un clic. Seul le cache du navigateur se limite aux derniers messages.
- Une pièce envoyée par une personne est à elle : une fois lue, le fil relu lui donne `id`, `url` et `available`, et `GET /files/<id>` la lui rend, à elle seule (le même 404 pour un autre compte), 410 une fois retirée. L'ADR 0106 (« elle ne renvoie jamais une pièce reçue ») vise les outils de Mika et ne change pas.
- Les pièces d'un message se lisent dans `attachments`, pas dans son texte : un message qui finit par des crochets n'annonce aucune pièce.

*Pourquoi :* on ne pouvait ni relire ni chercher sa conversation au-delà des 50 derniers messages, sans qu'aucune décision ait fixé cette limite, et une pièce envoyée ne se récupérait pas alors que le serveur la garde et que la maquette validée le permettait (audit du 5 novembre, Q12 et Q13).

*Révise 0062 (en partie : `/files/<id>` sert aussi les pièces de la personne), 0164 (en partie : `strand_history` lit aussi le fil avec elle).*

*Révisée par 0312.*

### 0233 — Le Téléphone ne montre que ce que le serveur sait

- Le Téléphone de frontendv2 n'a pas d'onglet Notifications tant que l'application ne lit que les messageries : rangé par appli, il redisait Messages. Il reviendra sous la forme de la maquette, un fil de vraies notifications (un colis, un rendez-vous), quand l'application lira d'autres apps (ADR 0190, *À venir*).
- D'ici là, Messages porte toutes les conversations lues ; le menu « Plus » d'un fil ne garde que « Lui en parler dans le chat » ; une adresse `#telephone/notifications` gardée retombe sur Messages.
- Ce que l'application lit se dit dans Paramètres › Téléphones (« Ce que ton téléphone lui montre »), pas dans un onglet de plus.
- Pas de choix de téléphone tant que chaque message ne dit pas le sien (0190, *À venir*) : la barre de titre du Téléphone dit un état, pas un menu — le nom du téléphone (« 2 téléphones » s'il y en a plusieurs), quand on l'a vu, et un point dont le sens se dit en mots (« ne reçoit pas les notifications ») —, et mène à Paramètres › Téléphones, qui les détaille. Partent avec le menu la note « tu vois ceux de tous tes téléphones », l'icône de réglages qui doublait ce lien et le nom du téléphone dans l'en-tête d'un fil. Le choix reviendra quand le serveur dira quel téléphone a reçu quel message.

*Pourquoi :* un onglet qui redit Messages et un menu qui y renvoie n'aident à rien ; rien ne se perd, la note est dans Paramètres et l'ancienne adresse retombe sur Messages ; l'onglet reviendra avec ce qui le justifie, comme 0190 le dit « à venir ». De même, un sélecteur qui promet un choix sans rien en faire trompe : choisir un téléphone ne triait rien et n'ajoutait qu'une note, il affichait « Tous tes téléphones 1 » pour un seul, et son point orange ne disait pas qu'il manquait les notifications ; l'état utile (quel téléphone, vu quand, notifiable ou non) tient dans la barre (audit du 2026-11-05, F3-03 et F3-04, décisions F3-Q1 et F3-Q2).

*Révise 0190 (en partie : l'onglet Notifications attend les notifications des autres apps, et le choix d'un téléphone que chaque message dise le sien).*

### 0235 — L'app Android, client de tous les jours

- L'application Android reprend ce que fait le frontendv2 (0187) : le chat et le mode pro, Mail, Teams, Carte, Téléphone, Outils et Paramètres, pour la personne connectée, sur la même API par personne (`/api/moi`). Sa maquette validée est dans `frontend/Android/maquette/`.
- On y navigue par un tiroir : le chat reste en plein écran, Mika en fond, comme avant. Sur chaque autre écran, son visage est au bout de la barre du haut et ouvre « Ce qu'elle fait ».
- Le jeton d'un téléphone (client `mobile`) écrit sur l'API par personne comme une session de navigateur, sans jeton CSRF : l'en-tête `Authorization` ne part jamais tout seul d'une autre page, et l'application ne présente pas d'`Origin`. Le jeton d'un autre client natif (`screen`) ne fait toujours que lire.
- Au-dessus du champ du chat, ce qui attend ta décision se replie sur une ligne (combien d'accords, combien de brouillons, le compte à rebours) ; dépliée, la carte d'accord dit exactement ce qui partira, et ses brouillons de mail et de Teams sont des liens vers l'écran où ils se décident (0191).
- La carte de l'application est MapLibre Native (sa version OpenGL ES), sur le seul fond que sert ce serveur (0193) : son style est tiré de celui du web par un outil (`frontend/Android/tools/carte_style.mjs`), ses requêtes passent par un client qui pose le jeton et refuse toute autre adresse ; ni télémétrie, ni tuiles par défaut, ni lien vers un tiers. Elle replie sur le plan dessiné quand le fond ne se lit pas.

*Pourquoi :* « peux-tu améliorer mon appli Android en reprenant les fonctionnalités de frontendv2 », puis, devant la maquette : « en mode tiroir je préfère ». Une API qui refusait l'écriture à un client natif laissait l'application en lecture seule, alors que le téléphone a déjà son jeton, révocable, et décide déjà des accords sur la socket.

*Révise 0187 (en partie : un client natif ne faisait que lire l'API). Révisée par 0296 (en partie : l'app a aussi l'écran Projets).*

### 0242 — L'app Android montre un mail HTML dans sa mise en page, dans une WebView qui ne fait qu'afficher

- La liseuse de l'application montre un mail HTML comme le client web : le document isolé du serveur (`/mail/frame`, 0169), ses images intégrées comprises. Un mail sans HTML garde son texte.
- Le document se lit sous le jeton puis se pose dans une WebView par `loadDataWithBaseURL`, sans adresse d'origine. La politique du cadre, qu'une page posée ainsi ne reçoit pas du serveur, s'écrit en tête du document (`<meta http-equiv>`), avant tout ce que le mail contient, avec « aucun référent ».
- La WebView n'exécute aucun script, ne lit ni fichier ni contenu de l'appareil et ne charge rien du réseau, sauf les images distantes quand elles sont permises. Elle ne navigue jamais : un lien web ou `mailto:` touché s'ouvre hors de l'application, tout autre lien ne fait rien.
- Les images distantes suivent 0175 : masquées, un bandeau propose de les afficher cette fois (`images=1`) et, pour une propriétaire qui écrit dans la boîte, toujours pour cet expéditeur, ou plus jamais.
- La WebView prend la hauteur de son contenu, et c'est la liseuse qui défile. Un mail plus large que l'écran s'y réduit et se zoome à deux doigts ; le texte suit la taille de police du téléphone. Un cadre qui ne se charge pas, ou un moteur de rendu perdu, rend le texte du mail et propose de réessayer.

*Pourquoi :* « les email html ne marche pas sur android » (2026-11-17). La liseuse ne montrait que le texte, et un mail sans version texte s'y réduisait à une note.

### 0252 — Un modèle libre par défaut ; le sien, s'il est là

- Le dépôt porte un VRM libre, `frontend/Web/public/models/mika-libre.vrm`, fait dans VRoid Studio : VRM 1.0, licence
  publique VRM 1.0 (redistribution et modification permises). Le modèle qu'on a acheté reste `default.vrm`, jamais
  versionné : sa licence (VN3) ne permet pas de le redistribuer.
- Les clients web essaient `default.vrm`, puis `mika-libre.vrm` : le client 3D (`vtuber/VTuberModel.ts::MODEL_URLS`)
  comme frontendv2 (`mika/vrm.ts::vrmUrls`, sous `/ext/models/`). `VITE_MIKA_VRM_URL` remplace les deux.
- Ce qui se publie (le README du dépôt, ses images) montre le modèle libre, jamais le modèle acheté.
- Le téléphone : *pas encore fait*. `frontend/Android/tools/vrm_mobile.py` ne lit qu'un VRM 0.x.

*Pourquoi :* le dépôt est public, et le modèle acheté ne peut pas y être. Un modèle libre « deviendra le modèle VRM par
défaut si on le remplace pas » (2026-11-20).

### 0282 — Les projets dans l'API par personne : ce qu'elle voit, « À faire », ses gestes

- **Ce qu'elle a d'un projet** est la plus serrée de deux lectures du moteur, jamais une règle de l'API : ce que ses lignes d'accès lui donnent hors de toute conversation (`todo.reach` : son projet en entier ; celui d'un autre seulement par une ligne qui la désigne partout et toujours, `links.given_to`), et ce que la conversation lui en dirait par le canal de son client (`access.sees`, `access.steering`), au niveau qu'elle en entend (`tracker.reader_of`). Le voir donne son titre et son état ; son détail demande de le piloter au moins en lecture seule et d'entendre son niveau. Un projet archivé, ou celui d'un autre sans ligne à son nom, n'existe pas (404). Un opérateur n'y a que les droits de sa personne.
- **Les routes** (`app/me/projects.py`, sous `/api/moi/projets`, `protocole-moi.md` § 11) : ses projets et « À faire » (`todo.for_person`, filtré par ce qu'elle a de chaque projet ; chaque entrée dit le geste qui la règle et si elle peut le faire ici) ; la fiche (missions, objectifs et leurs jalons, branche, pull request, CI, relecture, plan, listes, liens, dépôt) ; une page d'éléments, et un élément avec son fil. Un élément ne dit ses textes que si `tracker.veiled` les lui laisse lire ; un projet lié ne dit son numéro et son titre que si elle le voit elle-même, et ce que le lien donne vient de `links`. Un texte venu d'ailleurs (l'hôte du dépôt, un autre projet, la sortie d'une commande) porte `outside`.
- **Chaque geste passe par l'action de console qui le fait déjà**, au nom de la personne (audité `moi.projects.<action>`), après la garde que l'outil de conversation applique au même geste. Ouvrir un ticket et noter : qui pilote sur accord ou en modification — sur accord, le ticket naît proposé (`ticket_ouvrir`, `born`). Changer un statut, une consigne, « vas-y maintenant », la pause, la reprise : en modification seulement. Trancher un ticket ou un point d'arrêt : le propriétaire du projet, ou qui s'occupe d'elle (`tracker.settles`), une validation nommant le plan lu. Répondre à un plan : qui l'a demandé. Poser ce qu'il lit : son propriétaire (`links.may_link`).
- **Un accord** (un effet proposé dont le contexte est le projet) se donne par `runtime.decisions.decide`, sur le condensé de ce qui a été lu (`seen`, exigé pour accepter), par quelqu'un qui s'occupe d'elle : « ton accord », dans une ligne d'accès, est le sien, pas celui de la personne pour qui le projet est fait. Dans « À faire », un accord n'est à une personne que si elle peut le donner.
- **Restent à la console** : créer un projet et régler son cadre (outils, accès, dépôt, rythme), ajouter ou rouvrir un objectif, fermer un ticket comme traité ou le rouvrir, régler une liste, publier chez l'hôte. Un pilotage « sur accord » se demande dans le chat, où elle le propose. `GET /api/moi` compte ce qui l'attend (`counts.projects`).

*Pourquoi :* le client web et l'app Android n'avaient des projets que leur titre et les accords en attente, par le canal du chat ; leur écran « Projets » doit lire en une requête ce qui attend la personne, sans recalculer une règle ni montrer plus que la conversation ne lui dirait.

*Révise 0133 (en partie : piloter un projet et trancher se font aussi depuis l'espace de la personne, sous les mêmes gardes), 0187 (en partie : l'API par personne porte aussi ses projets). Révisée par 0286, 0288, 0289, 0290, 0293, 0297.*

### 0284 — L'écran Projets du client web : « À faire » d'abord, le geste sur place

- `frontendv2/` a un écran **Projets** (`src/screens/projets/`, sur `protocole-moi.md` § 11), deuxième rubrique, avec
  la pastille de `counts.projects`. Deux onglets : **À faire** (ce qui l'attend dans tous ses projets, dans l'ordre du
  serveur) et **Projets** (ses projets en cartes : où en est chacun, combien de choses l'attendent). Une fiche a cinq
  onglets : où il en est (ce qui attend, son plan, ses missions, ses objectifs avec leurs jalons, la pull request, la
  CI, la relecture), ses tickets, ses listes de suivi, ses liens, son dépôt en bref.
- **Chaque attente se règle sur place** : son bouton déplie ce qu'il faut lire (ce qui partirait, le plan du projet,
  celui d'un ticket, la question posée, les statuts de la liste), puis envoie la route et les arguments que le serveur a
  donnés (`gesture`), complétés par ce qui est saisi. Valider le plan d'un ticket nomme le plan montré ; un accord
  renvoie le condensé lu. Sur une liste de suivi, un statut se change d'un geste, sur la ligne même.
- **Le client ne recalcule aucune règle** : pas de bouton sans `can` ou `rights`, les libellés d'étape et de statut
  sont ceux du serveur, et il ne vérifie pas ce qui est saisi — un geste refusé se dit sur place, avec les mots du
  serveur (un 409 relit ce qu'on lisait). Piloter (consigne, lancer, pause, reprise) est dans la barre de titre, quand
  `rights.pilot` le permet.
- **Un texte venu d'ailleurs** (`outside` : une issue d'un inconnu, un commentaire de l'hôte, la fin d'un journal de CI,
  la sortie d'une commande) est cité dans un cadre à part (`markup.ts::outsideMarkup`) : échappé, sans lien ni
  balisage, jamais présenté comme un mot de Mika ou de la personne ; un lien venu d'ailleurs ne s'ouvre que s'il est
  http ou https, sans référent.
- **Restent à la console**, sans bouton ici, dits par une ligne là où on les chercherait : créer un projet et son cadre
  (outils, accès, dépôt, rythme), ses objectifs, fermer ou rouvrir un ticket, régler une liste, publier chez l'hôte. Ce
  qu'il lit ne se pose ici que si elle voit tous les projets lus (la route veut toute la liste). La barre du bas d'un
  téléphone a huit entrées ; Paramètres s'y dit « Réglages ».

*Pourquoi :* la personne doit pouvoir répondre à ce qui l'attend depuis son navigateur, téléphone compris — « j'ai
contacté cette entreprise » en un geste — sans que le client refasse une règle du moteur ni lise comme une consigne ce
qu'un inconnu a écrit. La maquette (`frontendv2/maquette/ecrans/projets.js`) reste la référence de sa forme.

*Révise 0187 (en partie : le client de tous les jours a aussi un écran Projets, et huit rubriques). Révisée par 0286, 0291.*

### 0286 — L'API des projets sert ses mots et ses raisons ; ce qu'un projet lit change lien par lien

- **Ce qu'un projet lit change lien par lien** : `POST /api/moi/projets/<id>/liens` nomme ce qui change (`add`,
  `remove`, et pour un lien posé `direct_on`, `direct_off`), plus jamais toute la liste. Elle ne nomme que des projets
  qu'elle voit : un lien vers un projet qu'elle ne voit pas reste tel quel, et le nommer se refuse comme un projet
  inconnu. La fiche dit ceux qu'elle peut lui faire lire, chacun avec ce que le lien donnerait (`candidates[].gives`).
  Les règles restent celles de `links` et de l'action `projects.liens`.
- **Une attente est comptée pour qui peut la régler** (`todo.awaits`) : la personne nommée, sinon le propriétaire du
  projet — sauf un accord, qui n'attend que qui s'occupe d'elle, même dans un projet confié à quelqu'un d'autre.
  `todo.for_person`, la console (« attend ») et l'API le lisent là ; l'API n'y ajoute que la carte adressée à
  quelqu'un, que le fait des effets en attente ne dit pas.
- **Une attente qu'elle ne peut pas régler ici dit pourquoi** (`why`) : le refus même que sa route rendrait, mot pour
  mot, ou l'endroit où le geste se fait (la console, l'hôte du dépôt). Une attente « chez l'hôte » porte l'adresse de
  la pull request (`gesture.url`), composée du dépôt et de son numéro (`pulls.pull_url`).
- **Les mots sont servis, les clients n'écrivent pas les leurs** : les sortes et les priorités d'un ticket avec la
  liste des tickets (`kinds`, `priorities`, et ce qu'un ticket reçoit par défaut), et qui a écrit un élément ou une
  note — sa sorte (`author_kind` : elle, la personne connectée, une autre personne, un autre projet, l'hôte) et ses
  mots (`author`).
- **Le nom d'une autre personne** ne se sert que si elle s'occupe d'elle (sa voix la nomme à tous), ou si ce qui
  concerne cette personne s'entend par ce client au niveau de l'élément (`vocab.privacy.hearable`) ; un autre projet
  ne se nomme qu'à qui le voit ; rien n'est nommé d'un élément qu'elle ne lit pas.

*Pourquoi :* l'écran Projets du client web butait sur ces manques — il écrivait ses propres mots, coupait « Choisir ce
qu'il lit » dès qu'un projet lu ne lui était pas visible, disait « pas d'ici » sans raison — et « À faire » comptait
pour le propriétaire d'un projet confié un accord qu'il ne peut pas donner ; l'app Android s'écrit sur la même API.

*Révise 0281 (en partie : `for_person` compte un accord pour qui s'occupe d'elle), 0282 (en partie : la forme du geste des liens, les champs servis, le nom d'un auteur), 0284 (en partie : ce qu'il lit se pose ici même quand elle ne voit pas tous les projets lus).*

### 0287 — L'effort d'une réponse se force depuis la conversation : pour toute la conversation, ou pour un fil

- **Deux réglages, « auto » ou forcé** : son opératrice force l'effort de réflexion des réponses qu'elle reçoit pour toute sa conversation avec elle (mode pro compris), et pour chacun de ses fils de travail. Un fil en auto suit la conversation ; la conversation en auto ne demande rien : le rôle décide (ADR 0285). L'ordre entier : le fil, la conversation, le rôle, la fiche du fournisseur, le défaut du modèle.
- **C'est un réglage gardé, pas un champ du message** : `transcript.effort_set` (la personne, le fil — vide pour la conversation —, l'effort — vide pour auto), projeté dans `thread_efforts` ; l'action `transcript.regler_effort` l'écrit, au nom de celle qui règle. Il vaut sur tous ses écrans, et un client qui ne le connaît pas en profite quand même. Oublier la personne l'efface.
- **L'épisode le lit quand il compose** (`EpisodeRunner.effort`, que la composition branche sur `transcript.asked_effort`) et le pose sur sa requête (`LLMRequest.effort`) : il vaut pour toute sa boucle d'outils, et sa trace le dit. Seulement pour la réponse à un message de la personne, en privé : ni une initiative, ni un salon, ni la seconde passe, ni un travail de fond.
- **Un candidat choisi peut demander le sien** (`effort` dans ses arguments, comme son mode) : il passe devant. C'est par là qu'un projet posera son effort préféré sur ses séances.
- **Dans le chat** : la trame `effort` le règle (opératrice authentifiée seulement, comme le mode pro), `effort_result` dit le sort, et `efforts` rend le réglage entier avec ce que « auto » vaut en ce moment — à l'ouverture et après chaque réglage. Une valeur que le code ne connaît pas ne demande rien.

*Pourquoi :* l'effort ne se réglait que dans la console, par rôle, pour tout le monde et pour toute tâche. Elle veut pouvoir demander plus (ou moins) de réflexion là où elle travaille — une question difficile, un fil de travail exigeant — sans changer le réglage de toute l'instance, et le retrouver d'un appareil à l'autre. Un champ porté par chaque message aurait laissé à chaque client le soin de s'en souvenir.

### 0288 — Le code d'un projet dans l'API par personne, et la fusion : le geste d'une personne

- **Le dépôt se lit à une référence, par le port.** `Workshop` lit le dépôt d'un atelier à une branche ou à un commit, dans les objets de git et jamais dans l'arbre de travail : ses branches et leur écart avec la base (`branches`), un dossier (`ref_tree`), un fichier (`ref_file` : son texte s'il en est un et qu'il tient sous la borne ; binaire, trop gros, lien symbolique ou sous-module, il se dit sans contenu), l'histoire d'une branche, de toutes ou d'un chemin (`history`), un commit (`change`) et ce qui change d'un commit à un autre, fichier par fichier, à lignes numérotées et borné (`diff_of`). Une branche se nomme par son nom validé, un chemin est relatif et ne remonte pas : rien ne sort du dépôt, et un lien ne se suit pas.
- **Les routes** (`app/me/project_code.py`, sous `/api/moi/projets/<id>/code`, `protocole-moi.md` § 11) servent les six vues de l'écran — fichiers, commits, branches, pull requests, issues, CI — sans rien laisser à recalculer : les mots à côté des codes, les adresses chez l'hôte composées ici, ce qui est lié (l'objectif, le ticket et son étape). Le détail d'un projet donne les titres et les états ; **le contenu d'un fichier et un diff demandent en plus le droit sur ses fichiers** — celui de ses lignes d'accès hors de toute conversation (`todo.reach`) et par le canal du client (`access.shares_files`), au niveau de ce que le projet écrit. Les pull requests, leur CI et leur relecture viennent du journal ; les branches, les commits et les diffs, de l'atelier ; l'hôte n'est lu que pour ce qu'il est seul à savoir (`RepoHost.talk` : les échanges ; `Checks.runs` : les vérifications une à une ; les issues et leurs étiquettes), borné par compte, et rien de ces lectures ne va au journal. Tout texte de l'hôte porte `outside` ; une issue d'un inconnu ne dit son titre et son texte qu'à qui peut la trancher.
- **Fusionner est le geste d'une personne, et de personne d'autre.** L'action `projects.fusionner` — dans la console sur la ligne de la pull request, et par `POST …/code/pull/fusionner` — est réservée au propriétaire du projet et à qui s'occupe d'elle (`tracker.settles`, la règle de qui tranche un ticket) : un opérateur qui n'est ni l'un ni l'autre ne fusionne pas. Elle nomme le commit de tête que la personne a vu, et se refuse si la pull request n'est pas prête (`merge.blocked` : pas ouverte, en conflit, des changements demandés, des vérifications en cours ou en échec, un commit pas encore envoyé, une fusion déjà demandée), si la branche a bougé dans l'atelier ou chez l'hôte, ou si l'hôte la dit impossible à fusionner. Acceptée, elle pose un fait, `projects.merge_asked` : qui, quelle pull request, quel commit.
- **La fusion part après le commit du journal, par le port** : l'effet de `merge_asked` — ni un outil, ni une capacité qu'une exécution pourrait proposer, ni un processus — appelle `RepoHost.merge_pull(numéro, sha)`. L'hôte ne fusionne que si le commit au bout de la branche est encore celui-là (chez GitHub : `PUT …/pulls/<n>/merge` avec `sha`) ; ce qu'il répond devient `projects.merge_answered` (fusionnée, ou pourquoi non : `moved`, `blocked`, `denied`, `unreached`), et une fusion interrompue n'est jamais rejouée. Le garde « rien ne fusionne » devient « seul le geste d'une personne fusionne » : `merge_asked` n'est écrit que par cette action, `merge_pull` n'est appelé que par cet effet, et l'adaptateur n'a qu'un `PUT`, celui-là.
- **Le moteur apprend cette fusion comme toute fusion** : `projects.pulls`, que la réponse réveille, relit la pull request chez l'hôte et pose `projects.pull_seen` — l'objectif est clos, son ticket traité, la base récupérée (0274, 0277). Aucun second chemin : la réponse de la fusion ne clôt rien elle-même. L'objectif garde où en est la demande (`merge_asked_at`, `merge_by`, `merge_answered_at`, `merge_refused`) ; l'état se reconstruit du journal (`state_version` 27). Le jeton n'a besoin d'aucun droit de plus : le contenu et les pull requests en lecture et écriture, comme pour ouvrir une pull request.

*Pourquoi :* l'écran Projets validé le 21 novembre a un onglet Code — fichiers, commits et leur diff, pull requests complètes, branches, issues, CI — et un bouton Fusionner que le propriétaire a demandé : son geste à lui, avec confirmation. L'API par personne ne servait rien du dépôt, et fusionner n'existait nulle part. « Elle ne fusionne jamais » (0274) tenait par l'absence de tout moyen ; elle tient maintenant par une seule porte, que seul le geste d'une personne ouvre, et que des gardes d'architecture surveillent.

*Révise 0183 (en partie : l'hôte se lit aussi depuis l'espace d'une personne, sous ses droits), 0274 (en partie : le port de l'hôte a de quoi fusionner, pour le geste d'une personne seulement ; elle ne fusionne toujours pas), 0275 (en partie : le port rend les vérifications une à une, les étiquettes d'une issue et les échanges), 0282 (en partie : l'API par personne sert le code d'un projet et fusionne ; fusionner ne se fait plus seulement chez l'hôte). Révisée par 0290, 0292, 0297.*

### 0290 — Gérer un projet depuis l'espace d'une personne : ce que l'écran montre s'y modifie

- **Chaque geste passe par une action de la console, après une garde du moteur** (`app/me/project_manage.py`, `protocole-moi.md` § 11). Le cadre d'un projet — ses réglages, ses outils, son dépôt, l'archiver, le restaurer : qui le pilote en modification **et** en est le propriétaire, ou s'occupe d'elle (`managing.frames`, la règle de qui tranche) ; piloter ne suffit pas. Lui confier un projet (`projects.projet_confier`) : qui s'occupe d'elle, comme `create_project` en conversation — il naît à cadrer, avec les mots de qui le demande. Ses objectifs (avec leur critère, « fini quand », que les deux formulaires d'un objectif portent désormais), ses jalons, ses tickets, ses décisions : qui le pilote en modification. Fermer un ticket comme traité et le rouvrir passent par « Trancher » : qui tranche. Sur l'accord du propriétaire, rien de tout cela d'ici.
- **Un jalon tenu ne se défait que par qui tranche.** `projects.jalon_modifier` et `projects.jalon_retirer` appliquent à une personne la règle de l'ADR 0278 (`managing.undoing`) : un jalon atteint ou retiré ne bouge plus, pour personne ; un point d'arrêt, un jalon posé par une personne, fixé par un plan validé ou refusé par le propriétaire reste au propriétaire du projet et à qui s'occupe d'elle. Les textes d'une décision qui n'est pas remplacée se révisent (`projects.decision_modifier`, le fait `projects.decision_revised`) ; un ticket se modifie sans changer d'étape (`projects.ticket_modifier`).
- **Écrire chez l'hôte sur une pull request est le geste d'une personne**, comme la fusion (0288) : `projects.pull_modifier` (son titre, son texte) et `projects.pull_commenter` — réservées au propriétaire du projet et à qui s'occupe d'elle — posent un fait, `projects.pull_write_asked` ; après le commit du journal, son effet appelle le port (`RepoHost.edit_pull`, un `PATCH` qui ne porte que ces deux champs ; `RepoHost.remark` pour un commentaire, avec son repère : jamais deux fois), et la réponse devient `projects.pull_write_answered`. Un commentaire part du compte du jeton : son texte dit qui l'écrit (la règle des notes publiées, 0275). Aucun outil ni aucune capacité n'y mène, une écriture interrompue n'est pas rejouée, et un garde le vérifie par l'AST.
- **Ce qui s'est passé se relit du journal** (`app/me/project_activity.py`) : le fil d'activité mêle ses exécutions, leurs commits, ce qui arrive à ses pull requests et à ses tickets, et les gestes des personnes — filtré par sorte et par objectif, paginé par curseur, compté par jour sur trente jours ; ses exécutions (cadrage, travail, relecture) et, pour l'une d'elles, ses pas lus dans sa trace — l'outil en mots, ce qu'il visait, jamais ce qu'il a rendu, un outil venu d'ailleurs marqué ; son carnet ; ses décisions. Le diagramme de ses objectifs ne porte que de vraies dates : quand un jalon a commencé et combien d'exécutions il a prises se déduisent des départs de ses exécutions, rien n'est estimé. Lire tout cela demande le détail du projet, au niveau de ce qu'il écrit.
- **Les réglages se servent tels que les actions les décrivent** (`kernel.forms` : le libellé, l'aide, les choix et la valeur de chaque champ, en cinq sections), et chaque objet dit ce que la personne peut en faire (`can`, `why`) : l'écran n'écrit aucun mot et ne montre un bouton que s'il marche. Un objectif bloqué se rouvre d'ici (« À faire » en porte la route). « Liens » s'appelle « Dépendances » — « Il dépend de », « Dépendent de lui », « Ses demandes » — dans les mots de l'API (`links.labels`) et de la console ; les identifiants et les adresses ne changent pas. La console n'a pas encore le formulaire des actions nouvelles.

*Pourquoi :* devant la maquette validée le 21 novembre, le propriétaire a dit « je ne vois pas de bouton edit de projet, d'ajout d'objectif ou de jalon » : l'écran Projets n'est pas une vue réduite qui renvoie à la console, ce qu'on y voit s'y modifie là où on le voit. L'API par personne laissait à la console le cadre d'un projet, ses objectifs et la fermeture d'un ticket, et ne servait ni ses exécutions, ni son carnet, ni ses décisions ; modifier un jalon, un ticket, une décision ou une pull request n'existait nulle part.

*Révise 0133 (en partie : le cadre d'un projet se change aussi depuis l'espace de son propriétaire, ou de qui s'occupe d'elle), 0145 (en partie : un projet confié depuis l'écran naît à cadrer, comme en conversation), 0275 (en partie : le commentaire d'une personne sur une pull request est signé comme une note publiée), 0278 (en partie : ce qu'une personne qui pilote sans être propriétaire ne défait pas d'un jalon), 0281 (en partie : l'onglet « Liens » s'appelle « Dépendances »), 0282 (en partie : le cadre, les objectifs, la fermeture d'un ticket ne restent plus à la console ; l'API sert l'activité d'un projet), 0288 (en partie : le port de l'hôte change le titre et le texte d'une pull request, pour le geste d'une personne). Révisée par 0292, 0293, 0297.*

### 0291 — L'écran Projets refait d'après la maquette validée : trois zones, tout se gère dans l'écran

- **L'écran de `frontendv2/` reprend la maquette validée** (`frontendv2/maquette/ecrans/projets2*`, le 21 novembre : « sers-toi de la maquette comme référence ») : ses adresses (`#projets/a-faire/<projet>/<attente>`, `#projets/projets/<id>/<onglet>/…`), sa structure, ses classes et sa feuille de style, reprise telle quelle (`src/styles/ecrans/projets.css`). L'écran rejeté — cinq onglets, le geste déplié dans une page qui empile — et sa maquette sont retirés.
- **Trois zones sur toute la largeur** (`parts.ts::trio`) : la liste, le contenu élastique découpé en volets (jamais deux grandes parties l'une sous l'autre), un panneau latéral (l'état, les propriétés, ce qui est lié avec son statut, les gestes). Sur un écran moyen le panneau se replie sous l'en-tête du détail ; sur un téléphone il devient le volet « Infos », et la liste puis le détail sont deux pages. Une fiche a ses onglets — Vue d'ensemble, Objectifs (la liste serrée, le détail, le diagramme en deux modes), Tickets, Code, Documentation, Activité (Fil, Exécutions, Carnet), Dépendances (le schéma, les demandes), et Listes pour un projet qui en a une ; Code et Documentation se branchent à part (`tabs.ts`).
- **Tout se gère dans l'écran**, là où on le voit (0290) : confier un projet, le modifier (ses réglages en sections, dont les champs sont ceux que le serveur décrit), l'archiver ; ajouter, modifier, rouvrir, terminer ou retirer un objectif ou une mission ; ajouter, modifier ou retirer un jalon, valider un point d'arrêt ; ouvrir, modifier, trancher, fermer ou rouvrir un ticket ; poser ou retirer une dépendance. Un ajout s'ouvre dans un panneau à droite, une modification dans la zone de contenu ; plus aucune phrase ne renvoie à la console.
- **Le client ne recalcule toujours aucune règle** : pas de bouton sans le droit servi (`can`, `rights`), les mots d'une étape sont ceux du serveur, un geste refusé se dit sur place avec les siens (un 409 relit ce qu'on lisait), et un texte venu d'ailleurs est cité dans sa présentation à lui, échappé (`parts.ts::outside`). Seules la couleur d'un état (`tones.ts`) et la mise en page se décident ici. **Ce que l'API ne sert pas ne s'invente pas** : la vue se fait avec ce qui existe.
- **Deux défauts de la maquette ne sont pas repris** : dans le diagramme « Dans le temps », l'axe se resserre (ou passe en semaines) pour que la première date et aujourd'hui tiennent à l'écran, et le mot d'une barre se retient au bord au lieu d'être coupé (`diagram.ts`) ; la hauteur d'un détail sert — un formulaire pose ses boutons en bas, le panneau pose en bas ce qui se gère, et prend deux colonnes quand le contenu est court alors qu'il déborde.
- **Code et Documentation** (`code.ts`, `documentation.ts`, leurs vues, branchés par `tabs.ts`) suivent les mêmes règles, et trois de plus. **L'éditeur d'une page est Milkdown, par son éditeur Crepe** (`@milkdown/crepe`, licence MIT : la bibliothèque que le propriétaire a vue dans la maquette) : chargé à la demande, dans son propre morceau, quand on ouvre le mode Modifier (`editor.ts`) ; son élément est gardé d'un dessin à l'autre ; Enregistrer envoie le Markdown avec la version lue et un mot, et un refus (la page a changé depuis) ne fait jamais perdre ce qui est écrit (`docparts.ts`, le brouillon). **Rien de ce qu'un dépôt ou une page contient ne s'exécute ni ne se charge d'ailleurs** : le contenu d'un fichier et les lignes d'un diff se posent par insertion de texte, jamais en HTML (`paint.ts`) ; une page lue passe par un rendu échappé (`docmd.ts`) ; en lecture comme dans l'éditeur, seules les images de l'espace de documentation, servies par l'API, sont chargées. **Fusionner passe par une confirmation** qui dit ce qui va être fusionné, et la demande nomme le commit de tête qu'elle vient de relire (`codeparts.ts`) — depuis la pull request comme depuis « À faire ».

*Pourquoi :* le premier écran, écrit sans que le propriétaire ait validé sa maquette, a été rejeté (« un one page dégueulasse », « moche et non fonctionnel ») ; la maquette refaite avec lui en trois tours fait foi, et l'écran doit être le même à l'œil.

*Révise 0284 (l'écran : ses onglets, le geste déplié sur place, ce qui restait à la console ; restent la rubrique, sa pastille, la règle « le client ne recalcule rien » et la présentation d'un texte venu d'ailleurs). Révisée par 0294.*

### 0292 — Ce que la relecture adverse des projets a fixé : le cadre réservé, la fusion et la CI, le point MCP, les pas, les fichiers cachés

- **Le cadre d'un projet ne donne pas ce qui n'est pas du projet.** Être le propriétaire d'un projet n'est pas s'occuper d'elle : ce qui ouvre autre chose que le projet lui-même est réservé à qui s'occupe d'elle (`managing.keeps`) — ses lots autres que sa mémoire et le web (le courrier, la caméra, ses flux, la Forge, ses apps, un service MCP : `managing.beyond`), l'accord de ce qui sort, pour qui il est, son dépôt distant (adresse, branche, flux, envoi automatique), la publication de ses tickets en issues. La garde est dans les actions (`actions.reserved_field`, `_held`), pas dans une route : la console et l'API par personne passent par elle. Son propriétaire garde le reste (titre, cadre, mode, rythme, relecture, validation des plans, mémoire, web). Les réglages disent champ par champ ce que la personne peut changer (`can`, `why`), et les services branchés sur l'instance ne se servent qu'à qui peut les cocher ; un projet qui n'est pour personne le reste tant qu'on ne nomme personne ; restaurer et lister les archives passent par la portée (`reach`), le nom du propriétaire par la règle des noms.
- **La fusion relit la CI, la base, et ne part qu'une fois.** Juste après un envoi, l'hôte n'a pas encore créé les vérifications du commit : tant que la pull request est fraîche (trois minutes après ce que l'hôte en a dit de neuf, `merge.CHECKS_GRACE_US`), « aucune vérification » ne laisse pas fusionner (`merge.UNCHECKED`) et l'hôte se relit chaque minute au lieu de dix. Au moment de fusionner, l'action relit chez l'hôte les vérifications du commit de tête — en cours, en échec ou illisibles, rien ne part — et la base où la pull request entre : autre que la branche du projet, rien ne part. Une seule demande à la fois par pull request (le fait `projects.merging`, gardé au commit du journal). Une réponse perdue après l'envoi se dit « on ne sait pas » (`MERGE_UNKNOWN`), jamais « n'a pas eu lieu », et l'hôte se relit aussitôt.
- **Le point MCP compte les appels, pas les requêtes** (`app/me/docs_mcp.py`) : chaque appel d'outil paie son passage dans la fenêtre de 120 par minute et par compte ; un lot porte vingt messages au plus (`protocol.BATCH_MAX`, pour tout point MCP) ; un projet reçoit au plus 200 écritures de documentation par MCP sur vingt-quatre heures, tous comptes confondus (gardé en mémoire). L'usage d'un jeton se note à ce point ; un jeton d'outil ne s'élague pas avec les connexions (vingt par compte, à part) et se rend lui-même (`DELETE /auth/token`).
- **Ce qu'une personne lit se compare à son droit, texte par texte.** Les pas d'une exécution ne disent ce qu'ils visaient — un chemin, une commande, une recherche, jamais un texte de contenu — qu'à qui a le droit sur les fichiers du projet, et sur ceux du projet lié qu'un pas vise ; sans lui, le libellé de l'outil seulement (`steps_aims`, `steps_aims_why`). Le fil, les exécutions et le carnet comparent chaque texte au niveau que son contenu porte au journal, pas à celui que le détail a aujourd'hui (`veiled`). Le refus d'une page périmée et le nom d'un jeton suivent la règle des noms (`_nameable`) ; hors de la console, l'action ne nomme personne.
- **Les fichiers cachés ne sortent pas, les secrets ne se commitent pas.** La règle du partage d'un fichier de projet (`ports.workshop.hidden_path` : un segment qui commence par un point) vaut pour l'arbre, un fichier, l'histoire d'un chemin et un diff servis par l'API (403 ; un diff dit le chemin et les comptes, sans ses lignes). `.env` et ses variantes ne s'enregistrent jamais dans le dépôt d'un atelier (son exclusion locale, non versionnée). Un commit n'est dit d'elle que signé et posé par l'adresse entière de l'atelier. Une image de documentation retirée puis remise à l'identique se remet (aucune clé permanente, des octets propres à chaque ajout), et la réponse dit ce que l'état a gardé.

*Pourquoi :* la relecture adverse des lots S1 à S3 (0288, 0289, 0290) a montré qu'un propriétaire de projet qui ne s'occupe pas d'elle se donnait son courrier, sa caméra et ses services, coupait l'accord et branchait un dépôt que le jeton de l'instance atteint ; qu'une fusion était offerte pendant que la CI tournait ; qu'un lot de messages passait la borne du point MCP ; et que des chemins, des noms et des textes sortaient sans le droit qui les garde.

*Révise 0104 (en partie : le courrier, la caméra et les autres lots réservés se donnent à un projet par qui s'occupe d'elle, pas par tout opérateur ni par son propriétaire), 0288 (en partie : la fusion relit la CI et la base chez l'hôte, une seule demande à la fois, une réponse perdue se dit « on ne sait pas » ; les fichiers cachés ne se servent pas), 0289 (en partie : la borne du point MCP compte les appels et les écritures ; l'ajout d'une image n'a plus de clé permanente ; le nom d'un jeton suit la règle des noms), 0290 (en partie : le cadre réservé à qui s'occupe d'elle ; ce que disent les pas d'une exécution ; restaurer passe par la portée).*

### 0293 — Ce que l'écran Projets attendait encore : le parcours en six étapes, le mot d'un lien, ce que chaque vue lit sans rien recalculer

- **Le parcours d'un ticket se sert en six étapes** — non lu, en analyse, validation, pull request, fusion, traité : celles que le propriétaire a données. La règle est pure et à côté de `stage` (`tickets.journey`, `tickets.step_of`) : chaque étape fine tombe dans l'une des six, dont elle reste la précision (proposé : non lu ; sa question posée : en analyse ; pull request en cours : pull request ; prête à fusionner : fusion) ; ce qui précède est passé, ce qui suit à venir. **Un ticket qui ne passe pas par une pull request saute « pull request » et « fusion »** (`tickets.through_pull` : son projet est au flux direct, ou il s'est fermé sans en avoir eu) : « validé, en cours », il n'attend plus que d'être traité. Fermé, une étape n'est passée que si un fait le dit ; écarté, il saute aussi « traité ». Les étapes fines restent servies comme avant.
- **Son histoire se rejoue, elle ne s'écrit pas** (`tracker.passages`) : les événements du ticket repassent par les règles mêmes de l'état (`added`, `changed`, `_noted`), une ligne par changement d'étape — quand, par qui. De même, un jalon est dit commencé (`milestones.begun`) dès qu'une exécution est partie depuis que le jalon d'avant est atteint, et le prochain passage d'un projet (`work.coming`) est ce que `next_run_at` date et ce que `pick` prendrait : rien n'est estimé.
- **Un lien garde depuis quand il est posé et le mot de son propriétaire** (`Project.ties`, `Tie`) : `projects.links_set` porte ce mot (`why`, `why_for` — pourquoi ce projet lit celui-là), un texte gardé, au niveau de ce qu'écrivent les deux projets, avec les sujets du lecteur et, pour l'oubli, ceux du projet lu (`read_about`). Un lien qui reste garde les siens, un lien retiré les perd ; l'état se reconstruit du journal (`state_version` 29). Ce mot est un texte du projet lecteur : du côté du projet lu, il ne se sert qu'à qui lit aussi le détail du lecteur. **« Lui demander quelque chose »** n'est pas une règle de plus : c'est l'ouverture d'un ticket chez le projet lié, avec les droits que la personne a sur lui ; la fiche dit si elle le peut (`ask_here`) et range ses tickets à côté des demandes du projet (0271), dans les deux sens.
- **Chaque vue lit ce qu'elle montre** (`app/me/projects.py`, `project_activity.py`, `protocole-moi.md` § 11) : la carte d'un projet dans la liste, son prochain passage, son rythme et ses consignes en attente, son dernier commit, le titre d'une pull request, les tickets d'un objectif, ce qui lie un jalon à un élément, les déclencheurs possibles d'une mission et les façons de vérifier un jalon avec leurs mots, ce qu'un accord concerne et où il part, le fil filtré par ticket et ses totaux. Les règles de droits sont celles d'avant (0282, 0286, 0292) : un projet lié ne se nomme qu'à qui le voit, la commande d'un jalon ne se dit qu'avec le droit sur les fichiers, les réveils de l'instance ne se servent qu'à qui s'occupe d'elle, chaque texte du journal se compare à son niveau.
- **Une liste de suivi se tient depuis l'écran** : y ajouter un élément (`projects.element_ajouter`) et changer à qui il est — à elle, ou au propriétaire du projet (`projects.element_confier`, une action de plus, que la console ne pose pas encore sur un onglet) —, pour qui le pilote en modification. La main sur un ticket ne se pose pas : elle se déduit de son étape.

*Pourquoi :* l'écran Projets, écrit d'après la maquette validée (0291), n'invente rien : là où l'API ne servait pas ce qu'une vue montre, il faisait sans — dix étapes de ticket au lieu des six du propriétaire, une carte vide tant que la fiche n'était pas lue, des dépendances sans date ni raison, un historique réduit à l'ouverture. Servir ces lectures par des règles pures du moteur garde l'écran sans règle à lui, et les droits là où ils sont déjà.

*Révise 0257 (en partie : un lien garde sa date et le mot de son propriétaire, `links_set` porte un texte et ses sujets), 0268 (en partie : changer à qui est un élément, par une action, depuis l'espace d'une personne), 0270 (en partie : le parcours se sert aussi en six étapes, déduites des étapes fines), 0282 (en partie : ce que l'API sert de plus d'un projet ; ajouter un élément à une liste ne reste plus à la console), 0290 (en partie : les totaux et le filtre par ticket du fil, les consignes en attente).*

### 0294 — L'écran Projets d'accord avec ce que l'API sert ; un fichier Markdown du dépôt se lit rendu

- **L'écran lit ce que l'API sert depuis 0293, et ne garde aucune liste à lui.** La grille remplit chaque carte de la liste (`card`) et ne lit plus aucune fiche ; la Vue d'ensemble et l'Activité disent le prochain passage (`next` : daté par le moteur, sinon ses mots), le rythme, les consignes en attente, le dernier commit ; un ticket montre son parcours en six étapes (`journey` : l'étape fine en précision, les étapes sautées dites), ce qui lui est lié (`linked`) et, dans l'Historique, l'histoire de ses étapes mêlée au fil d'activité filtré sur lui ; les formulaires d'une mission et d'un jalon proposent ce que la fiche sert (`forms` : déclencheurs, façons de vérifier, leurs mots et leurs champs) ; un accord dit ce qu'il concerne, où il part et pourquoi ; une dépendance dit depuis quand, pourquoi, le commit que montre la vue et les demandes dans les deux sens, et le mot du lien se saisit en la posant ; une liste de suivi s'y tient (ajouter, changer à qui est un élément).
- **Un champ réservé se montre verrouillé, avec sa raison** (`can`, `why` de chaque champ des réglages, 0292) : sa valeur se lit, rien ne s'y saisit, et il ne part jamais dans un enregistrement — plus de champ modifiable puis refusé. Une section dont aucun champ ne se change n'a pas de bouton.
- **Ce que le moteur ne sait pas ne devient pas un bouton.** Ce qu'un lien donne se lit (une coche, une croix), sans case ; « Lui demander quelque chose » ouvre un ticket chez le projet lu au nom de la personne (`ask_here`) et le dit — ce n'est pas une demande du projet ; il n'y a ni « objectif lié » dans le formulaire d'un ticket, ni suppression d'un projet, ni sorties réglées une à une, ni façon de fusionner, ni relance d'une CI, ni élément confié à une personne nommée.
- **Un fichier Markdown du dépôt se lit rendu, par le rendu des pages de documentation** (`docmd.ts`, `views/code.ts::renderedFile`), avec une bascule Rendu | Source : tout est échappé avant d'être mis en forme, **aucune image n'est chargée** (un dépôt n'a pas d'espace d'images : chacune se dit), un lien relatif mène au fichier du même dépôt, à la même branche (`codeparts.ts::repoLink` : jamais hors de sa racine), un lien http(s) s'ouvre à part, sans référent. La source d'un fichier et les lignes d'un diff restent posées par insertion de texte (`paint.ts`).

*Pourquoi :* la maquette validée montre ces lectures, et l'écran faisait sans tant que l'API ne les servait pas ; elle montre aussi le README rendu, que l'écran affichait en source par prudence — le rendu des pages, déjà éprouvé contre une page hostile, le permet sans rien exécuter ni rien charger. Un bouton qui ne fait rien, ou un champ qu'on remplit pour être refusé, apprend au propriétaire que l'écran ment.

*Révise 0291 (en partie : un fichier Markdown du dépôt peut passer par le rendu échappé des pages ; la grille ne lit plus les fiches ; ce que l'API a appris à servir se montre).*

### 0296 — L'écran Projets de l'app Android

- **L'app a sa rubrique « Projets »**, dans le tiroir juste après le chat, avec sa pastille (`counts.projects`) : ce que fait l'écran Projets du client web (0291, 0294), d'après la même maquette validée, lue dans ses vues en largeur de téléphone, sur la même API (`/api/moi/projets`, `protocole-moi.md` § 11) et sous le jeton du téléphone, qui écrit sans jeton CSRF (0235).
- **Sa forme est celle d'un téléphone : une liste, puis son détail en page, avec un retour.** La rubrique a deux volets, « À faire » et « Projets » ; la fiche d'un projet a ses onglets qui défilent en largeur (Vue d'ensemble, Objectifs, Tickets, Code, Documentation, Activité, Dépendances, et Listes quand le projet en a) ; ce que le web met dans son panneau latéral devient un volet « Infos » du détail ; un formulaire s'ouvre en feuille, par-dessus, sans quitter la vue. Aucune page n'empile tout.
- **L'app ne recalcule aucune règle** : ce qu'on peut faire vient du serveur (`can`, `why`, `rights`, `gesture`, `forms`) — pas de bouton sans le droit servi, un geste refusé se dit sur place avec les mots du serveur, les libellés d'étape et de statut sont les siens. Ses règles pures (quelle route et quel corps un bouton envoie, quelle couleur porte un état, comment une liste se range) sont portées du client web (`data/moi/projects/ProjectsRules.kt`) et testées sur la JVM. Un verdict sur un ticket passe toujours par `ticket/trancher`, même depuis une attente qui porte un autre geste (une pull request prête, dont le ticket s'écarte encore).
- **Un texte venu d'ailleurs** (`outside`) se montre comme tel — un liseré, « venu d'ailleurs », en texte brut, jamais mis en forme ; un texte d'elle ou de la personne se lit en Markdown par le rendu du mode pro (0116), qui n'interprète aucun HTML.
- **Le code et la fusion.** L'onglet Code a ses six volets (Fichiers, Commits, Pull requests, Branches, Issues, CI), chacun une liste puis son détail en page. Le contenu d'un fichier et les lignes d'un diff sont du texte : posés tels quels en chasse fixe, ils défilent en largeur dans leur cadre, jamais la page ; le diff est unifié, replié fichier par fichier ; un fichier Markdown se lit rendu, sans un lien qui s'ouvre ni une image chargée. **Fusionner est le geste d'une personne, confirmé** (0288) : la pull request se relit à l'instant, la confirmation dit ce qui va être fusionné, et la demande nomme le commit de tête qu'on vient de relire. **La route de la fusion n'a qu'un chemin dans l'app** — un seul appel, sur un ordre qui ne naît que d'une pull request relue que le serveur ouvre (`merge.can`) ; aucun geste générique ne la porte, depuis « À faire » comme ailleurs, et un test le garde.
- **La documentation, l'activité, les dépendances, les listes, modifier le projet.** La documentation d'un projet (0289) se lit et s'écrit dans l'app : ses pages, rendues par le même rendu — une image ne s'y charge que si elle est de l'espace du projet, par l'API et sous la session de l'app ; une image d'une autre adresse se dit, sans être chargée —, leurs versions, auxquelles on revient, ses images, ses décisions. **L'éditeur d'une page est natif, pas une vue web** : la bibliothèque d'édition du client web n'existe pas sur Android, et une vue web ouvrirait à du contenu ce que l'app n'ouvre nulle part. On y écrit du Markdown dans un champ ; une barre d'outils reste au-dessus du clavier et agit sur la sélection — ses transformations sont des fonctions pures, testées sur la JVM — ; une bascule Écrire | Aperçu ; une image se choisit par le sélecteur de photos du système, sans permission. Enregistrer nomme la version lue ; un conflit se dit avec les mots du serveur sans rien perdre du texte, qui vit dans le modèle de l'écran et survit à une rotation. L'activité (le fil et ses filtres, une exécution pas à pas, le carnet), les dépendances (le schéma, un lien en page, les demandes), les listes (un élément, son statut qu'on touche) et « Modifier le projet » suivent les mêmes règles : les champs d'un réglage sont ceux que le serveur décrit, et un champ qu'il réserve ne s'offre pas — il se lit, verrouillé, avec sa raison.
- **Livré en trois lots sur un même socle** : d'abord À faire, Projets, la fiche et sa Vue d'ensemble, Objectifs (la liste, le détail, ses formulaires, le diagramme) et Tickets ; puis Code ; puis Documentation, Activité, Dépendances, Listes, Modifier le projet, le mode « Dans le temps » du diagramme et les projets archivés.

*Pourquoi :* devant l'écran Projets du web, le propriétaire a dit qu'il en fallait un sur Android, puis « fais l'app android ». Un téléphone n'a pas la largeur des trois zones du web : la même maquette, lue à 390 px, donne la liste puis le détail, et le panneau latéral en volet.

*Révise 0235 (en partie : l'app a aussi l'écran Projets, à la place que la maquette du web lui donne dans la navigation).*

### 0308 — Les écrans en direct : ce qui change leur est poussé, le courrier arrive dès qu'il est là

- **Un service pousse ce qui change** (`app/me/changes.py`) : il écoute le journal (`Mind.subscribe`, comme le monde) et ce qui s'écrit hors de lui — les bases tenues à côté (le courrier relevé, Teams, l'annuaire, l'agenda), les comptes, les réglages, l'étape de son travail, la présence de l'extension Teams —, qui signalent chacune de leurs écritures une fois commitée. Il regroupe ce qui arrive en ~150 ms, puis pousse à chaque personne connectée une trame `changed` sur le `/ws` qu'elle a déjà ouvert : quoi a changé (une boîte, une conversation, ses brouillons, tes pastilles…), jamais le contenu. Un même sujet part au plus trois fois d'affilée, puis une fois par seconde tant qu'il revient (une boîte qu'on range des heures durant) ; ce qui attend son tour n'est jamais perdu. Une connexion lente ne retient personne : chaque trame part à part, en 5 s au plus, et ce qui suit pendant ce temps s'y réunit.
- **Seulement ce qu'elle peut voir** : la trame d'une personne ne nomme que ses ressources et celles qu'on lui partage, par les mêmes règles que `/api/moi` — une boîte d'une autre n'existe pas, même dans un avis. L'écran relit la route qu'il montre : les droits et la forme des données restent à un seul endroit. Ce qui change qui voit quoi (les propriétaires et les partages d'une boîte ou d'un compte Teams, les accès d'un projet, une adresse reliée à une personne, un réglage enregistré) part sans clé à toutes : le filtre lit l'état d'après, et celle qui perd l'accès doit le savoir aussi. Ces règles lisent l'annuaire et le cache de Teams hors de la boucle du serveur, que leurs lots tiennent sous verrou.
- **Le client a son service** (frontendv2 `src/live/`, l'app `data/moi/Live.kt`) : il reçoit `changed` et réveille les écrans abonnés ; à chaque (re)connexion, tout ce qui est affiché se relit une fois — rien de ce qui a changé pendant une coupure n'est perdu. Plus de relecture à intervalles (Mail, Teams, Téléphone, Contacts, pastilles, « elle s'y met ») ; un écran au second plan se relit à son retour.
- **Le courrier arrive dès qu'il est là, même endormie** : une connexion IMAP IDLE par boîte qui le permet (l'attente relancée toutes les 8 min, qu'un routeur n'oublie pas une connexion muette ; `imaplib` ne la sait que depuis Python 3.14), sinon une relève chaque minute ; ce qui arrive est rangé tout de suite dans le courrier relevé et se voit à l'écran. Elle, ne le remarque qu'à son rythme (éveillée, par sa relève et son tri), comme avant : ce qui est rangé attend sa relève en base (`offered`), comme ce qu'un autre client a lu entre-temps (`seen_elsewhere`), et rien n'est remarqué deux fois ni perdu à un redémarrage — au plus 1 000 de chaque par boîte, pour une relève qui ne passe plus. Une boîte observée ainsi a une seule règle pour sa panne : celle du direct. Seul ce qui change se dit : un mail rangé à l'identique, rien ; l'historique, une fois par passage et par dossier.
- **Teams sort sans attendre** : la boîte d'envoi part à l'extension dès qu'elle change (plus de relecture chaque seconde), et chaque étape d'un envoi (en cours, placé, parti) se voit aussitôt ; parti, ce que tu as écrit reste dans le fil jusqu'à ce que son jumeau y revienne par l'extension (5 min au plus). La présence de l'extension se pousse quand sa connexion en direct s'ouvre ou se ferme, et au plus toutes les 5 min quand elle se manifeste.
- **Une garde d'architecture** vérifie que toute écriture de ce qui est tenu hors du journal le signale : le courrier relevé, le cache de Teams, l'annuaire, l'agenda (une porte d'écriture, validée avant de dire), les comptes et les réglages (chaque méthode publique qui écrit) — sauf la tenue de la base que rien ne montre, excusée avec sa raison.

*Pourquoi :* « j'aimerais que les actions avec le frontend soient instantanées : réception de message, envoi, envoi de mail, réception. Tout ce qui entraîne des envois/réceptions d'information qui doivent modifier l'interface doit passer en temps réel à travers un websocket ; il faudrait un service qui gère tout ça » (le 2026-11-23). Choisis le même jour : le courrier en IDLE même endormie, frontendv2 et l'app Android dans le même chantier. La console et le client 3D ne changent pas ; les notifications Firebase de l'app fermée non plus.

*Révise 0027 (en partie : le courrier relevé en direct, à part de ce qu'elle en remarque), 0251 (en partie : la boîte d'envoi poussée sans relecture), 0306 (en partie : la ligne « elle s'y met » poussée, plus relue toutes les deux secondes).*

### 0312 — Les fichiers du chat : les revoir, les chercher, les reprendre

- **Tes pièces se montrent comme les siennes** (frontendv2, maquette validée le 2026-11-26 : `frontendv2/maquette/ecrans/chat-fichiers.js`) : une image en vignette, un document en carte (sa sorte, son nom, sa taille), barré d'un mot une fois retiré. Un clic l'ouvre dans une **visionneuse** : une image en grand, un PDF dans le lecteur du navigateur, un texte ou un Markdown (rendu échappé, ou source), un CSV en tableau, un son ; le reste se dit et s'enregistre ; « Enregistrer », « Dans la conversation » (le fil remonte jusqu'au message), ← et →.
- **« Fichiers » couvre toute la conversation**, pas les seuls messages chargés : `GET /api/moi/chat/fichiers` (`protocole-moi.md` § 14), page par page, cherché par **nom** (jamais dans le contenu ni dans ce qu'elle en a lu), trié par sorte et par qui l'a envoyé ; le fil avec elle, ou un fil de travail en mode pro. Ce qui ne se télécharge plus dit pourquoi.
- **Une pièce se reprend dès que ses octets sont gardés**, sans attendre que Mika l'ait lue de près : une lecture lente, retenue par le quota ou ratée (elle se retente plus tard) ne prive plus la personne de sa propre copie. Le serveur la rend à l'adresse qui l'a envoyée, ses octets vérifiés par leur clé ; sa taille n'est connue qu'à la lecture (0 d'ici là).
- **Rien n'est rendu ni exécuté** : `/files/<id>` reste un téléchargement (pièce jointe, `nosniff`, bac à sable, sans cache). L'écran en lit les octets une fois par session, les garde en mémoire (bornée) et ne lit une image qu'une fois parue à l'écran (60 téléchargements par minute) ; un PDF ne s'ouvre en PDF que s'il en a l'en-tête. Une pièce qu'on vient d'envoyer se revoit tout de suite, depuis la copie du navigateur.

*Pourquoi :* « quand on envoie une image ou un fichier texte ou PDF dans le chat on ne peut pas le reconsulter, ni en aperçu ni rien ; et dans Fichiers on ne peut ni les retélécharger, ni les rechercher, ni paginer, ni les consulter en modal » (le 2026-11-26). La bulle ne montrait de tes pièces que leur nom ; leur adresse n'arrivait qu'à la relecture du fil, et pas du tout tant que la lecture de près n'avait pas abouti ; « Fichiers » ne voyait que les messages chargés.

*Révise 0215 (en partie : la pièce se reprend avant d'être lue de près, et se liste sur toute la conversation).*

## La console et l'exploitation

### 0024 — L'exploitation : voir, sonder, sauvegarder, oublier pour de bon

- Chaque faculté déclare ses vues, en lecture seule ; l'inspecteur ne nomme aucune faculté. La persona éditée dans la console prime sur le YAML ; un secret n'est jamais réaffiché.
- La santé dit `ok`, `degraded` ou `ko`, et 503 tant qu'elle n'est pas prête ; `/health` est public et ne publie que des noms et des états.
- Une sauvegarde se prouve : un manifeste, des sommes, l'état rejoué depuis la copie ; `views.db` en est exclue. Restaurer vérifie avant de toucher au dossier, et met l'ancien de côté.
- Tout texte gardé dit qui il concerne : l'oubli efface par sujet, y compris ce qui citait la personne.
- L'unité systemd est durcie sans casser bubblewrap : ni `RestrictNamespaces`, ni `PrivateUsers`, ni `ProtectKernelTunables`.

*Pourquoi :* en v1, `/health` disait « ok » avec une boucle morte, la sauvegarde n'était jamais vérifiée et l'oubli laissait ce qui citait la personne.

*Révisée par 0025, 0054, 0101, 0125, 0135.*

### 0025 — La console : un back-office que les facultés déclarent

- Tout est déclaré, rien n'est nommé : les facultés déclarent leurs vues, leurs objets, des onglets sur la fiche d'un autre, leurs actions et leurs vitaux, en blocs du noyau.
- La carte est décidée par la composition et vérifiée au démarrage ; la console n'importe ni facultés ni plugins.
- Une action passe par le journal : validée champ par champ, ajoutée sous garde avec l'origine extérieure, auditée (`runtime.operated`) ; jamais sur ses souvenirs, ses pensées ou son humeur.
- La console garde de quoi dire « pourquoi ? » : le prompt envoyé, sa composition, les outils, les lignes de l'arbitre ; l'oubli les efface.
- Chaque paramètre porte un `Knob` borné et dit sa provenance (défaut ← tempérament ← réglage ← surcharge) ; un secret ne redescend jamais.
- Rien d'extérieur ne devient du HTML : gabarits échappés, politique de sécurité stricte.
- Revu par l'ADR 0121 : les pages sont dessinées à la main sur ce que les facultés déclarent ; seule la Forge garde le rendu générique.

*Pourquoi :* retrouver l'extensibilité des vues déclarées de la v1 sans que la console connaisse une seule faculté.

*Révise 0024 (en partie). Révisée par 0027, 0029, 0042, 0121, 0169, 0203, 0230, 0237.*

### 0029 — La console refondue : des menus qui répondent à des questions, des pages qui ne montrent qu'un sujet

- La carte répond aux questions d'un opérateur (que dois-je faire, comment va-t-elle, qui connaît-elle, que fait-elle et pourquoi…), jamais à l'organisation du code.
- Toute table est paginée : aucun plafond silencieux.
- Une page de configuration ne montre qu'un sujet ; chaque entrée d'une liste a sa page ; un envoi sur la page d'une autre section est refusé.
- Chaque faculté a sa page de paramètres : sens, valeur, provenance, bornes, et un retour au tempérament.
- Un champ ne se montre que s'il sert ; un choix limité est un sélecteur ; chaque champ a son aide.
- Ce qui manquait se voit : épisodes en cours, files, baux, approbations, file de sortie, modèles en service, coûts, résolution réelle des rôles.
- Une clé tapée n'est jamais renvoyée dans la page ; une sauvegarde absente, vieille de plus de deux jours ou en échec se signale.

*Pourquoi :* des menus rangés par propriétaire, des tables plafonnées sans le dire, toute la configuration sur une page.

*Révise 0025 (en partie). Révisée par 0042, 0121, 0173.*

### 0042 — La console dit pourquoi, en mots, et ne laisse rien partir par erreur

- Une page « Pourquoi a-t-elle dit ça ? » par parole dit en mots ce qui l'a fait parler, ce qu'elle avait sous les yeux et ce dont elle s'est souvenue ; le choix montré est celui de l'arbitre, exact.
- Tout se nomme au même endroit, par la composition ; les erreurs se disent en français, jamais en `repr`.
- Rien ne part par erreur : Entrée ne décide jamais une approbation, « Approuver » se confirme, une action d'opérateur est gardée sur ce qu'elle a lu.
- Les réglages refusent ce qui ne peut pas marcher ; un fuseau inconnu fait vivre le noyau en UTC, et la santé le dit.
- « Que ferait-elle ? » montre pour une personne ce qui la pousse, ce qui la retient et quand elle agirait, en lecture seule.

*Pourquoi :* un fuseau inventé mettait la console en panne, Entrée approuvait, et « pourquoi a-t-elle dit ça ? » demandait cinq onglets.

*Révise 0025 (en partie), 0029 (en partie).*

### 0045 — Les bords, l'exploitation, la console : ce qui passait entre deux lots

- La restauration prend le verrou du dossier : sous un autre processus, elle refuse sans rien toucher (code 3). `mika.lock` n'est pas archivé.
- Une seule façon d'opérer : la CLI passe par les actions de la console (mêmes refus, même garde, même audit). L'oubli emporte la clé, sa clé canonique et ses alias.
- Jamais une question orpheline : un tour qui ne recevra pas de réponse (file saturée, trop tard, elle dort) le dit une fois.
- Une capacité coupée se dit « on ne sait pas si elle a eu lieu ». On ne relance ni une parole périmée ni une action peut-être faite : elles vont dans « À traiter ».
- La console nomme tout ce qui existe, en français, et les gens par leur nom.

*Pourquoi :* une restauration pouvait écrire sous un serveur vivant, la CLI oubliait moins que la console, et la console parlait en identifiants.

*Révisée par 0056, 0135.*

### 0057 — La mise en route, l'exploitation et Telegram

- « Configuré » veut dire « elle peut répondre » : le premier fournisseur déclaré sert `reply` d'office ; un choix explicite n'est jamais changé.
- La santé est « dégradée » quand les derniers appels de `reply` échouent tous ; une annulation ne compte pas.
- `/` mène à la console ; sans aucun compte, sa page de connexion crée le compte opérateur, refusé dès qu'un compte existe.
- Une persona invalide n'arrête pas Mika : l'erreur est dite en français (fichier, ligne, cause, remède) et le serveur repart sur la dernière gardée.
- Telegram : retiré par l'ADR 0060.

*Pourquoi :* d'une installation neuve à sa première réponse, les pièges étaient silencieux : `/health` disait `ok` quand chaque tour échouait.

*Révisée par 0060.*

### 0103 — La constellation : sa mémoire en une boule de points, et ce qui la parcourt

- `/inspecteur/constellation`, réservée aux opérateurs, montre tout, secrets compris ; WebGL2 écrit à la main, sans bibliothèque (politique de sécurité de la console).
- Chaque point est un élément de l'index des vecteurs ; sa direction vient de ses dix voisins de sens (un plongement de voisinage posé sur la sphère, graine fixe) ; les filaments sont ces voisins.
- Une carte recalculée part de la précédente, sans sauter ; au-delà de 50 000 vecteurs, seuls les plus récents y sont, et la page le dit.
- Rien ne bouge pour faire joli : chaque trajet est un événement du journal (une parole et sa provenance, une naissance, la nuit, un rêve, un oubli).
- Les textes ne partent qu'à la demande (point survolé ou ouvert) ; sans lecteur depuis 30 s, rien n'est trié. La recherche prend ce qui contient les mots, puis ce qui ressemble au-dessus de 0,4.

*Pourquoi :* les tables de la console ne montraient ni sa mémoire d'un coup d'œil, ni ce qui la traverse.

### 0121 — Elle, en ce moment : une page dessinée à la main, qui croise ses facultés

- Une question qui traverse les facultés a sa page dessinée à la main, composée dans `app/` ; les blocs déclarés restent la règle pour la longue traîne, et l'inspecteur ne nomme aucune faculté.
- Pages faites à la main : l'accueil, « En ce moment » (humeur, plan plaisir × éveil, 24 heures sur un axe, corps, besoins, les gens), Personnes, et la vue d'ensemble d'une personne en premier onglet de sa fiche.
- Les onglets des destinations sont dessinés sur les données de leur faculté ; un dessin qui échoue ou ne reconnaît pas sa forme rend la main aux blocs.
- Toute page passe par les mêmes macros ; seules les vues de la Forge gardent le rendu de la console (`plain_owners`).
- Rien en ligne (politique de sécurité) ; un graphe a une hauteur fixe et s'étire en largeur seulement ; une partie qui échoue tait sa carte, jamais la page.
- Le menu et les onglets disent la même chose : une destination a un seul lien, ou un lien par onglet, dans leur ordre et sous leur nom.

*Pourquoi :* les blocs génériques rendaient tout pareil, et aucune page ne répondait à « comment va-t-elle, et pourquoi ? ».

*Révise 0025 (en partie), 0029 (en partie). Révisée par 0123, 0176, 0177, 0178, 0181.*

### 0122 — Régler ses outils, et ce qu'elle expose en MCP

- Un opérateur règle chaque outil par situation (`off`, `hand`, `ask`) ; une règle ne fait que restreindre, après la porte du code, et n'offre jamais ce que le code n'offre pas.
- Les règles passent par la seule porte d'offre, lues à chaque épisode (`tool_rules`) ; une lecture en échec n'applique rien. Un outil qui clôt une boucle ne se règle pas ; un réveil ou un murmure n'a pas de situation.
- La console en MCP se gère depuis la page : un jeton montré une seule fois, et ce qu'elle sert choisi dans une liste blanche de pages de lecture (`SERVABLE`).
- Des points de prêt (`/mcp/pret/<nom>`) prêtent à un agent des outils choisis, avec les droits de l'opératrice qui les a déclarés, relus à chaque appel ; ce qui sort passe toujours par son accord.
- Un point : la boucle locale, un jeton (`mlp_…`, empreinte seule), 60 appels par minute ; en lecture seule, toute écriture au journal est refusée à l'exécution.

*Pourquoi :* la console montrait ses outils sous tous les angles sans permettre de rien décider.

*Révisée par 0123, 0126, 0128, 0133, 0134, 0289.*

### 0123 — Le bloc Outils, redessiné

- Quatre entrées : « Ce qu'elle peut faire », « Venus d'ailleurs », « Prêter à un agent », « Apps forgées » ; les anciennes adresses redirigent.
- « Ce qu'elle peut faire » est une seule grille : familles en lignes, situations en colonnes ; une case là où le code offre l'outil, la décocher le retire dans cette situation.
- La place fine (« sous la main », « à chercher ») se règle sur la fiche de l'outil, et seulement là, quand le fournisseur diffère vraiment.
- Grille et fiche lisent les mêmes règles que la porte (ADR 0122) ; un seul enregistrement, audité par situation changée.
- Les familles portent un nom lisible, jamais l'identifiant du code.

*Pourquoi :* trois pages montraient les mêmes données avec trois vocabulaires venus du code, et l'on n'y comprenait rien.

*Révise 0122 (en partie), 0121 (en partie).*

### 0125 — Une restauration ne sort pas de son dossier

- La restauration travaille dans le dossier de données même : l'archive y est préparée (`.restauration-…`), l'ancien contenu mis de côté (`.avant-restauration-…`), puis chaque entrée prend sa place. Rien ne s'écrit dans le dossier parent.
- Le verrou reste en place, comme ce que la sauvegarde ne prend pas (`cache/`, le modèle de plongements).
- Ces dossiers cachés n'entrent dans aucune archive et aucune restauration suivante ne les remplace ; on les supprime à la main.
- Une mise de côté qui échoue remet l'ancien contenu à sa place ; une pose interrompue dit où se trouve l'ancien contenu.

*Pourquoi :* en service, l'utilisateur `mika` n'écrit pas dans `/var/lib` : échanger deux dossiers voisins y échouait, et root ne se connecte pas à MariaDB sous le compte `mika`.

*Révise 0024 (en partie).*

### 0126 — La console en MCP s'ouvre au réseau, si on le veut

- Une opératrice peut ouvrir `/mcp/console/` au réseau (Outils › Prêter à un agent) : le point répond alors à une autre machine, mandataire compris. Le jeton reste exigé, et la lecture seule ne change pas.
- Fermée par défaut. L'ouverture demande un jeton, se ferme d'un bouton, et fermer le jeton la ferme aussi ; un jeton neuf rouvre la console en local seulement. Chaque changement est audité.
- Ouverte, la ligne `claude mcp add` prend l'adresse par laquelle on lit la console ; fermée, celle de la machine (`127.0.0.1:8001`). La ligne finit par `/`, ce qui évite la redirection.
- Le relais de Claude Code et les points de prêt (`/mcp/pret/<nom>`) restent sur la boucle locale ; le mandataire ne relaie de `/mcp/` que `/mcp/console/`.
- Sans TLS, le jeton passe en clair : on ne l'ouvre ainsi que sur un réseau local.

*Pourquoi :* Mika vit sur un portable, et son opératrice lit sa console depuis une autre machine. Sans ouverture, il fallait un tunnel SSH, à rouvrir après chaque redémarrage.

*Révise 0122 (en partie).*

### 0169 — Un mail HTML se lit tel qu'il a été écrit, dans un cadre isolé

- Un document HTML natif (un mail reçu) s'affiche avec ses styles et sa mise en page, dans un `<iframe sandbox>` vers `/inspecteur/document/<empreinte>`. La page de la console n'en reçoit que l'adresse ; sa politique n'admet de cadre que du même serveur (`frame-src 'self'`).
- Le cadre a sa propre politique : styles en ligne, images `data:`, rien d'autre. Bac à sable sans `allow-scripts` ni `allow-forms` : rien ne s'y exécute, rien ne s'y envoie, rien ne remplace la console. `allow-same-origin` sert seulement à mesurer sa hauteur.
- La source est purgée en plus de la politique : scripts, cadres, objets, `<meta>`, `<base>`, gestionnaires `on…`, toute adresse autre qu'un lien web ou `mailto:` vérifié. Les liens s'ouvrent dans un nouvel onglet, sans référent.
- Les images distantes restent masquées : une image bloquée laisse son texte de remplacement, à sa taille. Les images `data:` s'affichent.
- La page garde le document en mémoire, par empreinte, le temps que le cadre le charge (64 au plus) ; après un redémarrage, recharger la page le redonne. La version simplifiée (`readable_html`) reste le repli sans cadre et la version texte reste dépliable.

*Pourquoi :* reconstruit sans CSS, un mail mis en page (colonnes, encadrés, boutons) devenait illisible. Le bac à sable garde la console aussi sûre qu'avant, sans priver le mail de sa forme.

*Révise 0025 (en partie). Révisée par 0172, 0175.*

### 0173 — Les réglages du courrier vivent dans le Courrier, en haut à droite

- Courrier › Paramètres s'ouvre par un bouton en haut à droite de chaque page du courrier (`Destination.gear`) : ce n'est pas un onglet de plus, et la barre de côté ne porte plus de lien vers les réglages.
- La page réunit ses boîtes, en cartes (où chacune en est, comment elle lit et envoie, sa voix, son dernier relevé), et les paramètres généraux du courrier (relevé, ce qu'elle en dit, ses brouillons), jusque-là seuls sous Réglages › Paramètres avancés. Une boîte se modifie sur la même page, chaque sujet à côté de ce qu'il règle.
- Une page de réglages peut ainsi vivre là où l'on se sert de ce qu'elle règle (`SettingsPage.home`, `params`, `template`) : ses liens et ses retours y mènent, un formulaire refusé s'y remontre. Elle s'enregistre toujours par les réglages et les paramètres, avec leurs gardes, leur audit et leur journal.
- L'ancienne adresse, Réglages › Plugins › Boîtes aux lettres, mène à la nouvelle.
- Tous les onglets du courrier et de ses fiches sont dessinés (ADR 0121), le brouillon disparu de la boîte compris.

*Pourquoi :* les réglages du courrier étaient loin du courrier, sous une autre mise en page et sans ses paramètres généraux ; ceux d'une boîte s'étalaient en grille de trois colonnes.

*Révise 0029 (en partie). Révisée par 0174, 0175, 0185, 0206.*

### 0174 — Le formulaire d'une boîte ne montre que ce qui sert, et suit ce qu'on tape

- Une boîte se règle dans cet ordre : la boîte (l'adresse d'abord, puis son nom court), la connexion, lire, envoyer, sa voix. La connexion vaut pour lire comme pour envoyer : elle a sa ligne, avec l'utilisateur et, selon le choix, le mot de passe ou l'application Microsoft.
- Ce qui ne sert pas au choix fait ne paraît pas (`Knob.only`) : le mot de passe ou l'application Microsoft, « Ton nom » ou « Son nom d'expéditrice ». Les réglages d'envoi et sa voix attendent un serveur d'envoi (`Knob.unless` : masqué tant qu'un autre champ vaut l'une de ses valeurs, vide ici) ; tant qu'il manque, la page dit ce qu'elle attend. Un champ masqué ne s'écrit pas.
- La console suit chaque changement, à la frappe comme au choix (`console.js`, `data-only` et sa négation `chemin!=valeur`). Sur une boîte neuve, l'adresse d'un fournisseur courant propose ses serveurs, leurs ports et la connexion ; un compte Microsoft choisi propose ceux de Microsoft ; l'utilisateur suit l'adresse ; un port suit son chiffrement (`static/handmade/courrier_boite.js`). Rien de ce qu'on a tapé ou choisi n'est écrasé. Ces fournisseurs sont une aide à la saisie, gardée dans le script ; sans lui, tout se tape à la main.
- Partout dans la console, une liste dont chaque choix est une valeur et qui ne peut rester vide n'offre plus de « — ».

*Pourquoi :* la connexion par Microsoft était rangée sous « Lire », ses deux champs obligatoires sous « rarement utiles », et rien ne réagissait à la connexion, à la voix ni au serveur d'envoi. Sans serveur d'envoi, la voix ne sert pas : un brouillon d'une boîte qui ne peut pas envoyer est refusé. Le « — » ne menait qu'à « choisissez une valeur ».

*Révise 0173 (en partie).*

### 0175 — Le courrier au quotidien : ton non-lu, sa lecture à part, ranger d'un coup, ses images, ses outils

- Dans la console, « non lu » est le tien : le drapeau du serveur, que la console ou un autre client posent. Ce qu'elle a lu ou rangé elle-même (`Seen.by_her`) se montre à part (« lu par elle », « archivé par elle ») et ne sort plus un mail de tes non-lus. Ses outils gardent leur sens (ADR 0168).
- Ouvrir un mail ne le marque toujours pas lu, sauf si le réglage « Ouvrir un mail le marque lu » (Courrier › Paramètres, Lecture) le demande : dès l'ouverture, ou après 3 ou 10 secondes passées à le lire, onglet visible. Le script de la console envoie alors « Marquer comme lu » ; sans lui, rien ne change.
- La boîte se lit comme une messagerie. À côté, ce qu'on lit (Réception, À traiter, Suivis, ses brouillons, Envoyés, Contacts), puis les comptes et leurs dossiers, sur chaque page : ils remplacent les onglets, que la page tait. La liseuse se place à côté de la liste dès que la place le permet, dessous sinon. Elle donne le message précédent et le suivant (j, k ; Échap la ferme) et, en tête, ce qu'elle en sait : ce qu'elle en a retenu, son tri, sa réponse. « À traiter » : ce que son tri juge attendre une réponse, sans réponse partie.
- Chaque ligne a sa case ; la barre au-dessus range ce qu'on a coché sur le serveur (lu, non lu, archiver, suivre, ne plus suivre, corbeille ; jamais de suppression définitive d'un coup). Les gestes courants du message sont à portée, « Lui demander une réponse » à côté de Répondre ; déplacer et jeter restent dans « Plus d'actions ».
- Ses images distantes restent masquées (ADR 0169), sauf si on les permet : pour ce mail (`?images=1`), ou « Toujours pour cet expéditeur ». La liste de ces expéditeurs vit dans les réglages (`mail_images`), à part des comptes ; oublier le correspondant l'en retire. Le cadre garde alors ses images `http`/`https` (ni `srcset`, ni attribut `background`) et se sert sous sa politique (`FRAME_CSP_REMOTE`), qui n'ouvre que les images, sans référent.
- Elle range elle-même (`email_tidy`) : marquer lu ou non lu, suivre, archiver, déplacer, mettre à la corbeille, jusqu'à 25 mails à la fois, jamais une suppression. Le résultat dit, mail par mail, ce qui est fait, ce qui l'était déjà, ce que le serveur a refusé, et chaque mail que tu n'avais pas encore lu : il informe sans interdire. Ce qu'elle range ne lui est plus signalé. C'est un outil qui agit, réservé à sa propriétaire par le minimum vital et réglable dans Réglages › Droits ; tant qu'un outil natif ne sait pas attendre un accord, « demande à la personne » et « demande-toi » ne lui font pas de carte.
- Un point de prêt qui n'écrit pas (ADR 0122) refuse un outil qui agit avant qu'il ne coure : la lecture seule ne bloquait que l'écriture au journal, et un rangement sur le serveur serait passé.

*Pourquoi :* un mail qu'elle avait lu disparaissait de tes non-lus ; ouvrir un mail ne le marquait jamais lu, et « Marquer comme lu » était caché ; tout se rangeait mail par mail, en ouvrant chacun ; la liseuse tombait sous la liste, à faire défiler à chaque mail ; ce qu'elle savait d'un mail ne se lisait que sur sa fiche ; une lettre d'information restait sans ses images ; elle ne pouvait ni trier ni ranger ta boîte.

*Révise 0027 (en partie), 0168 (en partie), 0169 (en partie), 0173 (en partie).*

### 0176 — La console redessinée : la navigation en haut, trois gabarits, un onglet par écran

- Plus de menu à gauche : les rubriques sont en haut, chacune un menu de ses pages, une ligne d'explication par page ; sur un écran étroit, un panneau. « Aller à… » (Ctrl K, `/`) trouve une page de la console puis cherche partout (`/recherche` ; sans script, le formulaire). Son état tient dans une pastille (son humeur, son énergie, les alertes) qui se déplie sur ses vitaux ; le thème et la déconnexion sont dans le menu du compte.
- Fond blanc, des filets plutôt que des aplats gris ; Inter servie par la console (`static/fonts`, `font-src 'self'`), Inter Display pour les titres, plus de serif ; trois arrondis (6, 4, 3 px) ; pas d'ombre, sauf sur ce qui flotte ; des contrôles de 32 px, 44 sur un écran tactile.
- Une action est à côté de ce qu'elle touche. Celles de la page (écrire, relever, ajouter, brancher) sont dans sa barre de titre, à droite du titre, la première en avant, les dangereuses sous « Autres actions », la roue de ses réglages (`gear`, ADR 0173) au bout : un onglet dessiné les y remonte (`Drawn.render` rend un triplet), un panneau les y nomme (`page_links`). Celles d'un objet sont sur sa ligne, sa carte ou sa fiche. Enregistrer est dans la barre d'enregistrement du formulaire, une seule.
- Trois gabarits. Le client : ce qu'on lit à gauche, la liste, la liseuse à côté (ADR 0175). Le paramétrage : une ligne par réglage, son nom et son aide à gauche, sa valeur à droite, deux par rangée quand la place le permet ; la barre d'enregistrement passe au premier plan dès qu'une valeur change ; une page à plusieurs sujets se lit en sous-onglets, une colonne à gauche (Courrier › Paramètres, les paramètres avancés) ; le tempérament se règle comme une table de mixage, tous ses curseurs d'un coup, le milieu marqué, l'aide du curseur touché à côté (`SettingsSection.aside`). La vue d'un objet : un seul bandeau d'alerte, une bande de chiffres qui mènent à leurs onglets, puis des tuiles.
- Un onglet tient dans un écran autant que possible : ce qui dépasse devient un onglet ou un sous-onglet, une liste se pagine.

*Pourquoi :* le thème était trop gros, trop rond, gris en clair ; le menu de gauche mangeait la largeur ; les actions changeaient de place d'une page à l'autre, et des pages défilaient sans fin.

*Révise 0121 (en partie). Révisée par 0177, 0297.*

### 0177 — Chaque onglet a sa forme : plus de rendu bloc par bloc

- Chaque onglet d'une destination a sa page à lui : un module par destination (`app/handmade/tabs/`) déclare ses onglets, chacun avec son gabarit (`templates/handmade/<destination>/`) et sa feuille. Le rendu bloc par bloc ne sert plus aucun onglet ; `test_every_drawn_tab_is_a_tab` y veille.
- Un onglet lit les blocs que sa faculté déclare, rendus une fois et numérotés comme la console les numérote (`Got`) : leurs ancres, leur pagination, la bascule « Tableau » et les jetons de leurs formulaires restent ceux de la console. Il lit aussi les faits d'une faculté quand ses blocs ne disent pas ce que la page montre.
- La vue de la faculté reste la source : la console en MCP la sert telle quelle, et un onglet qui ne reconnaît pas ses blocs (un titre changé) rend la main à la console. Un onglet dessine aussi son état vide ; sa racine porte son nom (`data-tab`), que `test_every_drawn_tab_opens` vérifie.
- Les filtres et le panneau d'un onglet restent ceux de la console, sauf s'il les dit lui-même (`Tab(panel=False)`).
- Une page qui a besoin de ce que sa vue ne dit pas le fait ajouter à la vue (une colonne, repliée au besoin), plutôt que de le relire à côté : un moment de « La vie des autres » dit sa situation, son issue et s'il se fête, lus dans l'archive (un moment sorti de la mémoire de travail les garde) ; une ligne de l'arbitre porte son calcul pas à pas, un veto par étape, sa sorte, sa cible et le rythme maximal de sa sorte — Décisions ne relit ni l'arbitre ni le journal.
- L'en-tête suit la maquette de l'ADR 0176 : le fil d'Ariane d'une destination dit sa rubrique puis la destination (« Mika / Humeur et corps », séparés par « / »), le titre reste celui de l'onglet (le menu nomme chaque onglet) ; des filtres de petits choix (quatre au plus, toujours posés) sont des boutons à choix au bout de la barre d'onglets, appliqués d'un clic ; « Fiches / Tableau » et les autres bascules ont le même dessin ; un bouton est en graisse 500.
- Les actions de la barre de titre suivent la maquette : deux en vue, la principale (la première déclarée) à droite des autres, le reste et les dangereuses sous « ⋯ ». Une fiche dit sa rubrique, sa destination et son numéro (« Activité / Projets / n° 257 »), son état en étiquettes à côté de son nom, ses faits sur une ligne ; ses onglets peuvent dire leur compte (`Overview.counts`), les plus rares sous « Plus ».
- « À valider » est une seule file et une seule page : tout ce qui attend une décision (les demandes d'envoi, les identités à confirmer, les noms à relier), ses onglets en sont des filtres (tout, les courriers, Teams, les identités, les noms) puis l'historique ; la composition déclare ces onglets et fournit ce qui n'est pas une demande d'envoi (`InspectorDeps.queue`), sans que l'inspecteur nomme une faculté. Courrier › Brouillons et Teams › Réponses restent dans leur destination pour retoucher un texte ; l'accueil ne compte la file qu'une fois.
- Les demandes en attente se lisent comme un courrier : la file à gauche, une ligne chacune, la demande ouverte à droite, la suivante après chaque décision ; seule la demande ouverte calcule son aperçu ; elle dit sa source en liens (que la composition fournit : l'inspecteur ne nomme aucun plugin) et son historique (l'épisode qui l'a proposée, les dernières décisions du même genre). La fiche d'un projet ne décide plus ses demandes sur place : son bandeau mène à la file.
- Une page d'action se pose déjà orientée par son adresse (`?valeur.<champ>=`) : un choix offert, un texte ou un objet, jamais une case « Je confirme », un secret ni un champ caché ; l'opératrice relit et envoie elle-même. Une action peut aussi tirer de l'état ses valeurs de départ (`initial=`) : relier un moyen de communication propose la personne que sa revendication vise, un démenti le nom revendiqué.

*Pourquoi :* la plupart des onglets restaient des blocs génériques (63 sur 79) : tous se ressemblaient, et aucun ne suivait les gabarits de l'ADR 0176.

*Révise 0121 (en partie), 0176 (en partie). Révisée par 0178, 0180, 0183, 0201, 0202, 0218, 0281, 0297, 0310.*

### 0178 — Le menu montre les groupes de pages

- Le menu d'une rubrique montre ses groupes de pages : une destination à onglets y est une colonne, son nom et sa ligne d'explication, puis ses onglets ; une page sans onglets n'a que son nom, et les pages seules qui se suivent partagent une colonne. Le menu ne nomme plus, à plat, les onglets d'une destination à côté d'une autre destination donnée en un seul lien.
- Les onglets d'une colonne sont ceux de la barre de sa page, lus au même endroit (`UI.tab_bar`) : `app/console_menu.py` ne nomme que la destination, et une vue ajoutée par une faculté y paraît d'elle-même. Une rubrique qui n'est qu'une destination (« À valider », « Système ») nomme ses pages une à une ; « Réglages » reste un choix de raccourcis.
- La page courante allume sa destination et son onglet ; une fiche n'allume un onglet que si l'on vient d'une liste. Les compteurs sont sur les onglets. « Aller à… » trouve chaque onglet, sous le nom de sa page.
- Moins de 1320 px de large : trois colonnes par rangée ; dans le panneau d'un écran étroit, les colonnes l'une sous l'autre, les onglets deux par rangée.

*Pourquoi :* le menu de sa rubrique mettait sur le même rang les sept onglets d'« Humeur et corps », les quatre de « Pensées et nuits » et « Mémoire » seule, qui en a huit : on ne voyait ni quelles pages vont ensemble, ni qu'il y avait d'autres onglets derrière une entrée.

*Révise 0121 (en partie), 0177 (en partie). Révisée par 0202.*

### 0179 — La fiche d'une personne réunit ses fichiers : reçus et envoyés

- L'onglet **Fichiers** de la fiche d'une personne montre ce qu'on lui a envoyé et ce qu'elle a envoyé, en deux sous-onglets : les pièces reçues d'abord (leur place, puis chaque pièce et ce qu'elle y a lu, ADR 0106), les fichiers envoyés ensuite (ADR 0062). L'onglet « Pièces reçues » quitte la barre ; son adresse (`?onglet=pieces`) mène à Fichiers, ouvert sur elles (`#pieces`). Mémoire › Pièces reçues et Place des pièces ne changent pas.
- Les deux restent des vues de leur faculté (`shares`, `attachments`), qui ne se connaissent pas : c'est la composition qui les réunit (`Overview.joined`, un onglet → ceux qu'il porte). La console exécute chaque vue et les passe à l'onglet dessiné en une `Section` chacune, la sienne d'abord ; leurs filtres restent ceux de l'onglet qui porte, et une forme qui ne se reconnaît pas retombe sur ces sections.
- Deux listes sur une page ont chacune leur pagination (`page_recues`, `page_envoyes`) ; une page plus loin rouvre son sous-onglet.

*Pourquoi :* deux onglets voisins pour une seule question (« quels fichiers entre elles ? »), l'un lu de son côté, l'autre du sien.

*Révisée par 0182.*

### 0180 — Les identités à confirmer et les noms à relier ne se décident que dans « À valider »

- Identités perd ses onglets **Identités à confirmer** et **Noms à relier** : il garde Moyens de communication et Règles de divulgation. Ces deux demandes ne se décident plus que dans la file « À valider », sous ses onglets du même nom.
- Les anciennes adresses (`/inspecteur/identites/revendications`, `/inspecteur/identites/noms`) mènent à la file (`approbations/identites`, `approbations/noms`), la requête avec elles. Le bandeau et la bande de chiffres de Moyens de communication y mènent aussi, et les actions d'une revendication y ramènent.
- Les deux vues de la faculté restent : la file les lit (ses entrées, son compte), la console en MCP les sert par leur nom. Elles sont hors de la navigation (`hidden`), et une destination ne fait plus d'onglet d'une vue cachée (`Inspection.in_section`) ; leur badge garde sa place, la destination d'Identités.

*Pourquoi :* la même demande se lisait à deux endroits, sous deux formes (une liste dans Identités, la liseuse de la file), et l'opératrice se demandait lequel faisait foi.

*Révise 0177 (en partie : Identités ne montre plus ses files). Révisée par 0298.*

### 0181 — Conversations s'ouvre sur les personnes, et chaque conversation est sur sa fiche

- Le premier onglet de Conversations est **Par personne** (`transcript`, vue `conversations`) : une ligne par personne avec qui elle parle, ses moyens de communication réunis (`identity.PERSON`), la conversation la plus récente d'abord. Elle dit par où, le dernier message et s'il est d'elle, combien de messages, les questions qui attendent sa réponse ; elle mène à l'onglet Échanges de sa fiche, ou au fil du moyen de communication d'une inconnue de passage. La vue se pagine elle-même (vingt-cinq par page), se filtre par nom ou moyen de communication (`handle`, un moyen nommé tel quel d'abord) et laisse de côté ses adresses internes. Un mot cherché (`q`) ne garde que les conversations où il a été dit, chacune montrant le dernier message qui le contient : c'est là que mène la recherche de la console (« Dans les textes »), qui ne propose plus une vue cachée.
- Dessinée comme Teams › Conversations : l'avatar prend la couleur de ce qu'elle ressent envers la personne et dit sa présence, comme sur Personnes.
- Le fil de tous les messages, toutes personnes mêlées, n'est plus une page de la console. La vue `messages` reste cachée (`hidden`) pour la console en MCP. Son adresse (`fil/messages`) mène à Par personne, son filtre gardé, et « Leur conversation » d'une demande à valider mène à la fiche de la personne.
- L'onglet Échanges d'une fiche (et le fil d'un moyen de communication) se lit les plus récents en premier, comme les pages de la faculté : la journée la plus récente en haut, et dans la journée le dernier message d'abord.

*Pourquoi :* toutes les conversations entremêlées dans un seul fil ne se suivaient plus dès qu'il y avait du monde. Une réponse tombait entre les messages de deux autres personnes, une page ne couvrait plus que quelques heures, et rien ne disait avec qui elle parle ni qui attend.

*Révise 0121 (en partie : la page d'entrée de Conversations, l'ordre des échanges). Révisée par 0241.*

### 0182 — Mémoire › Pièces reçues dit aussi la place de chacun

- Pièces reçues et Place des pièces ne font plus qu'un onglet de la Mémoire : la place en chiffres en tête (celle de chacun, en tout), puis deux sous-onglets, les pièces et la place par personne (une jauge chacune, vers ses pièces). L'onglet « Place des pièces » disparaît ; son adresse (`/inspecteur/memoire/place`) mène à Pièces reçues, ouvert sur la place (`#pieces-place`).
- Une seule faculté (`attachments`) : sa vue `recues` rend les deux listes, chacune avec sa pagination (`page`, `page_personnes`) ; une page plus loin rouvre son sous-onglet. Ses filtres (chercher, la sorte) ne portent que sur les pièces.
- Une ancienne adresse d'onglet peut mener à un sous-onglet : sa cible (`MOVED_TABS`) porte une ancre, posée après la requête.

*Pourquoi :* la place que prennent les pièces ne se lit qu'avec elles ; deux onglets voisins pour une même chose, comme les fichiers de la fiche d'une personne (ADR 0179).

*Révise 0179 (en partie : Mémoire › Pièces reçues et Place des pièces changent).*

### 0183 — Le dépôt git d'un projet face à son distant, issues et pull requests comprises

- L'onglet Dépôt git d'un projet est dessiné (`app/handmade/subjects/project_git.py`) : l'atelier et son dépôt distant face à face, l'écart entre eux (à pousser, à récupérer) et les gestes qui le comblent — « Pousser maintenant », « Récupérer » (les actions d'avant, avec leur accord) et « Relire » (une lecture neuve du distant) ; puis, en sous-onglets, l'historique de l'atelier (ceux qui restent à pousser marqués), ce qui n'est pas enregistré, l'histoire du distant (ceux à récupérer marqués), ses issues et pull requests ouvertes, les échanges passés et les réglages du distant.
- Un nouveau port, `repo_host` (`ports/workshop.RepoHost`), lit l'hôte d'un dépôt distant pour la console : la tête de la branche et ses derniers commits, les issues et pull requests ouvertes. Seul GitHub se lit (`adapters/workshop/github.py`, son API) ; pour un autre hôte, pousser et récupérer marchent comme avant, et la page le dit.
- L'écart se compte dans l'atelier quand il connaît la tête du distant (`Workshop.compare`, `git rev-list --left-right`) ; sinon l'hôte compare le dernier commit de l'atelier à sa tête. S'il ne connaît pas ce commit, ou s'il ne répond pas, l'écart est inconnu et la page ne montre pas de chiffres.
- Le jeton est celui des dépôts git. Il ne part à `api.github.com` que si `github.com` est parmi ses hôtes autorisés ; sans lui, un dépôt public se lit quand même. Ni redirection suivie ni réponse de plus de 2 Mo ; un délai de six secondes ; les liens montrés sont composés à partir du dépôt et d'un numéro, jamais repris de la réponse.
- Une lecture se garde deux minutes (une erreur, trente secondes). « Relire » la refait, pas plus d'une fois par dix secondes, et un envoi ou une récupération postérieurs aussi (`since`).
- Rien de ce que GitHub dit n'entre au journal ni dans ce qu'elle lit : c'est une vue de l'opératrice, pas un fait de sa vie. La vue `git` de la faculté porte ces blocs (la console en MCP, le repli) ; l'aperçu de la console a un hôte de démonstration (`app/apercu_git.py`), et les tests un GitHub hors ligne (`tests/conftest.py`).

*Pourquoi :* l'onglet ne montrait que l'atelier. Pour savoir s'il fallait pousser, si le distant avait bougé, ou ce qui attendait sur GitHub (une issue, une pull request), il fallait aller voir ailleurs.

*Révise 0177 (en partie : l'onglet Dépôt git est dessiné). Révisée par 0274, 0275, 0281, 0288, 0297.*

### 0197 — Les pages de réglages : des rubriques qui disent ce qu'elles contiennent, des formulaires qui n'écrasent rien

- **Une rubrique dit ce qu'elle contient.** « Canaux » ne nomme plus que les tableaux de droits par canal (ADR 0134). La rubrique de l'annuaire qui réunissait Notifications du téléphone, Carte de sa position, Lieux et adresses et Itinéraires devient « Carte et téléphone », avec son lien dans le menu Réglages et une barre d'onglets commune à ses quatre pages ; Dépôts Git, que le menu joint par Connexions extérieures, s'y range sous ce nom ; la clé de la rubrique Plugins suit son libellé (`plugins`, plus `sens`). Ces clés ne sont pas des adresses : les anciennes (`canaux`, `sens`) restent des adresses d'enregistrement (`LEGACY_POSTS`).
- **Une correspondance peut rester vide.** Chaque ligne de Qui sert quoi, de Qui dessine quoi et d'Où elles écrivent garde son « — » : la clé absente, le rôle retombe sur son repli, le flux part en premier jet. La règle de l'ADR 0174 (pas de « — » dans une liste qui ne peut rester vide) ne vaut pas pour elles : appliquée, elle faisait enregistrer la première option de chaque ligne laissée vide. Une correspondance que sa section décrit ligne à ligne (`SettingsSection.describe`) est une table, sa liste dans une colonne et ce qui la sert vraiment à côté : un seul formulaire, un seul Enregistrer.
- **L'annuaire est complet.** Tous les réglages liste aussi les pages qui vivent ailleurs (Courrier › Paramètres), dans leur rubrique ; chaque page s'y dit en une phrase entière, jamais coupée ; la recherche lit aussi le nom et l'aide de chaque champ et dit où elle a trouvé (`settings_directory.find`, que la recherche de la console peut reprendre).
- **La vue des plugins a une ligne par plugin composé**, tirée d'une table qui en a une par paquet de `plugins/` (un test les compare) : ses pages de réglages, ses paramètres avancés si sa faculté en a, où s'en servir ; puis ce qui se branche sans être un plugin (la transcription, les notifications du téléphone). Elle est dessinée, sans pagination.
- **Les commandes d'une page sont ses actions**, dans la barre de titre (ADR 0176) : « Nouveau jeton » en vue, « Revenir au fichier » sous « ⋯ », confirmées ; plus de carte « Commandes ». Un renvoi vers une autre page est un lien dans les faits de la page, dit une fois. Une entrée de liste s'intitule par elle-même (« Fournisseur « apercu » », « Fournisseur à ajouter »). Les valeurs et les bornes des Paramètres avancés s'écrivent en notation décimale française (« 0,00000556 », jamais « 5.56e-06 » à côté de « 0,0005 »).

*Pourquoi :* un nom doit dire ce qu'il y a dedans, et un mot ne doit avoir qu'un sens dans la console. L'audit du 2026-11-05 a vu qu'enregistrer Qui sert quoi figeait tous les replis, que l'annuaire oubliait les boîtes aux lettres et que la vue des plugins en oubliait quatre.

*Révise 0193 (en partie : la carte de sa position se règle sous Réglages › Carte et téléphone), 0194 (en partie : les lieux et les itinéraires aussi). Révisée par 0219 (en partie : une entrée neuve s'intitule « Ajouter un fournisseur »).*

### 0201 — À valider : un seul lecteur du contexte d'une demande, un historique par demande tranchée

- **Un seul lecteur du contexte.** Ce qu'une demande concerne se lit en un seul endroit, côté composition (`app/handmade/approval_sources.py` : `concern`, `about`, `sources`) ; l'inspecteur le reçoit du fournisseur de la file (`InspectorDeps.queue.about`) et ne nomme aucun plugin. Un canal (`teams`, `email`, `phone`) n'est jamais une personne. Une nouvelle sorte de contexte s'ajoute là, jamais dans l'inspecteur.
- **Pas de puce qui répète un onglet.** Sur « Tout ce qui attend », une sorte qu'un onglet de la file garde n'a pas de puce ; « Toutes » ne se compte pas : l'onglet le dit.
- **Ce qui sort de la machine se montre avant l'accord.** Une capacité sans aperçu montre ses arguments un par ligne ; la clé et le JSON exact restent repliés. Pousser et récupérer déclarent un aperçu (où, quel commit, ce qui part ou arrive), dont le condensé épingle l'accord ; un projet disparu, archivé ou sans dépôt distant le bloque.
- **L'historique compte des demandes tranchées** : paginé par décision, avec leurs exécutions relues ; une exécution sans décision n'y figure pas. Il se filtre par sorte (des puces) et par issue (un bouton à choix) ; l'issue se lit hors du journal (un booléen JSON ne se compare pas pareil sous SQLite et MariaDB).

*Pourquoi :* le contexte d'une demande se lisait de trois façons (la file, ses sources, l'historique), si bien qu'une réponse Teams menait à « La fiche de teams » ; l'inspecteur nommait des plugins par chaîne ; les puces de sorte répétaient les onglets ; un envoi au dépôt distant s'approuvait sur un JSON brut, et l'historique se paginait par événements, sans filtre (audit du 2026-11-05 : C1-01, K0-17, C1-06 à C1-08).

*Révise 0177 (en partie : la file, ses sources et son historique).*

### 0202 — Le menu fait foi : un nom par page, un fil d'Ariane qui part de sa rubrique, Système en trois colonnes

- **Un nom par page.** Une destination porte le nom de son lien au menu (« Ses sens », « Buts et rappels », « Ses outils ») ; le titre d'une page reprend le nom que le menu lui donne, ou son fil celui du lien qui la couvre. Le menu dit « Comptes » (tous les comptes : qui se connecte, qui pilote la console) et « Gestes audités » (ce que chacun a fait, dans la console ou depuis son espace).
- **Un seul fil d'Ariane, qui part du menu** (`Pages.trail`) : la rubrique du lien qui mène à la page — le plus précis ; à précision égale, celui de la rubrique où vit sa destination (`catalog.menu_place`, que le menu allume aussi) —, puis sa destination ; pour Réglages et Système, le lien qui couvre la page ou sa colonne (« Réglages / Paramètres avancés / Émotions », chaque niveau menant à sa page) ; la page n'ajoute que ses niveaux à elle (un numéro, un nom) : une fiche dit l'objet par son numéro, ou par sa clé quand il n'a pas d'autre nom (un serveur extérieur, « Outils / Ses outils / web », comme un outil) ; un objet que son titre nomme autrement (une personne, un mail) s'arrête à sa destination, sa clé interne ne se dit pas. Un retour ne le remplace plus : celui que déclare une faculté (`Head.back`) devient le lien de la destination quand il y mène, et se dit à part, au bout du fil, sinon ; la liste d'où l'on vient aussi (« ← Retour à la liste »).
- **Système en trois colonnes**, comme des groupes de pages (`MenuLink.column`) : Surveiller, Journaux, Anatomie ; Journaux mène aussi aux historiques des réglages et des autorisations, qui restent dans leur rubrique. Dans Réglages, les pages derrière un même lien forment sa barre d'onglets, dans l'ordre du lien, et chaque page de réglages appartient à un seul lien (Carte et téléphone a le sien, ADR 0197).
- **La recherche** trouve aussi un réglage par le nom de ses champs (les entrées de l'annuaire), et écrit ses dates comme le reste de la console. Les vues brutes des facultés n'y sont plus une sorte de résultat : un lien mène à Système › Toutes les vues.

*Pourquoi :* une même page portait trois noms (menu, fil, titre) ; le fil changeait de règle d'une page à l'autre (un mot seul, « Retour aux messages », un groupe que le menu ne montre jamais) ; quatorze pages à plat dans Système ne se parcouraient pas, et les journaux de qui a fait quoi étaient dans trois rubriques (audit du 2026-11-05).

*Révise 0177 (en partie : le fil d'Ariane de toute page part du menu, et un retour ne le remplace pas), 0178 (en partie : Système en trois colonnes, ses Journaux joints aux historiques).*

### 0203 — D'où vient un geste audité

- **Le début de sa clé d'audit le dit** : `console.…` (une action déclarée faite dans la console garde sa clé nue), `moi.…` (l'espace d'une personne : `perform(via=SPACE)` pour une action déclarée, `moi.<geste>` pour un réglage), `cli.…` ou `by` « ligne de commande ». `operations.origin` le lit ; Système › Gestes audités le montre et le filtre. Le contrat `runtime.operated` n'a pas de champ de plus.
- **Tout chemin de l'espace d'une personne le dit, sans exception** : une action déclarée passe `via=SPACE` (`Call.act`, ou `perform` quand le chemin a besoin de sa propre clé d'envoi) ; un geste qu'il audite lui-même a une clé `moi.…`, qui garde le titre de l'action déclarée quand c'en est une (`moi.teams.cle`). Un test le garde par l'AST, sur `app/moi/` et `app/mindport.py` (`tests/protocol/test_audited_gestures.py`).
- **Toute clé auditée a un titre** : celui de l'action déclarée, sinon `inspector/names.py::GESTURES` (un test l'exige). Une clé nue d'un geste d'avant se lit par les comptes : un opérateur, la console ; sinon, son espace.

*Pourquoi :* le journal des gestes mêlait ce que les opérateurs font dans la console et ce que chacun fait depuis son espace (frontendv2, le chat), sous un titre qui ne parlait que des opérateurs ; une même action ne se distinguait pas selon d'où elle venait (audit du 2026-11-05 : C9-08).

*Révise 0025 (en partie : un geste audité dit d'où il vient).*

### 0204 — Les voyages d'une personne se voient dans la console, et un opérateur peut en supprimer un

- La fiche d'une personne a un onglet **Voyages**, seulement si elle en a (`plugins/trips/inspect.py`, dessiné par `app/handmade/person/voyages.py`) : chaque voyage, du plus récemment changé, avec son titre, son départ, comment on s'y déplace, ce qu'il évite, s'il a été préparé avec Mika ; ses arrêts jour par jour, repliés (leur sorte, leur note, leurs coordonnées, « ajouté par » elle, sous son nom) ; son GPX.
- **Le GPX** est servi par la console, aux opérateurs seulement (`/inspecteur/voyages/<id>/gpx`) : le même document que l'écran Carte donne à la personne, ses arrêts et, quand les itinéraires le calculent, son tracé (vers le serveur d'itinéraires ne partent que ses points, comme depuis l'écran Carte). La console a la même limite que l'écran Carte, et la partage : chaque tracé demandé compte dans la borne du compte de l'opérateur, avec ses propres trajets de l'écran Carte (20 par minute ; au-delà, 429 et un message) — le serveur d'itinéraires public est à tous. Un GPX sans tracé à demander ne compte pas.
- **Supprimer** est le seul geste de la console sur un voyage : l'action `trips.supprimer`, posée sur chacun, confirmée, journalisée et auditée comme toute action (Système › Gestes audités : qui, depuis la console, la personne de la fiche, l'événement écrit). Elle vérifie toujours que le voyage est à qui agit ; dans ce seul cas, un opérateur (un compte opérateur actif, tel que l'identité le tient) qui agit depuis la fiche d'une personne (`ActionContext.subject`) atteint aussi le voyage de cette personne. La personne ne le retrouve plus.
- **Pas d'édition** depuis la console : un voyage se prépare à deux, la personne dans l'écran Carte, Mika en conversation. L'API par personne ne change pas : le voyage d'une autre personne y reste introuvable (404), même pour un opérateur.

*Pourquoi :* la console est l'espace des opérateurs, et les voyages étaient la seule donnée d'une personne qui en était absente : on ne les retrouvait que ligne à ligne dans le journal, et seul l'oubli de toute la personne les effaçait. Supprimer est le geste d'administration minimal (audit du 2026-11-05, décision Q06).

*Révise 0195 (en partie : la page de la console qu'elle remettait à plus tard).*

### 0205 — Les fichiers envoyés se voient tous ensemble, et un opérateur retire un fichier à l'unité

- **Mémoire › Fichiers envoyés** (la vue `envoyes` de `shares`, à côté de Pièces reçues, dessinée par `app/handmade/tabs/memory.py`) : ce qu'elle a envoyé, à tout le monde, du plus récent au plus ancien — sa sorte, pour qui, sa taille, son origine (écrit, dessiné, un fichier de projet), le message qui l'a emporté, son état ; le télécharger. En lecture : on n'y fait que retirer.
- **Retirer** un fichier envoyé (`shares.retirer`) ou une pièce reçue (`attachments.retirer`) : sur sa fiche, sous « ⋯ » comme toute action dangereuse, et sur sa ligne — l'onglet Fichiers de la fiche d'une personne, Mémoire › Pièces reçues et Fichiers envoyés, dont les onglets dessinés préparent le formulaire, le fichier pour objet. Confirmé, journalisé et audité comme toute action (Système › Gestes audités : qui, quel fichier). Seul un fichier dont les octets sont encore là se retire.
- **C'est le retrait de la rétention, à l'unité** : le même événement (`shares.expired`, `attachments.expired`), avec une raison de plus, `operator` (`contracts/shares.py`, `contracts/attachments.py`), que les facultés réduisent comme les autres. Les octets s'effacent après le commit. La ligne reste, estompée, « retiré par un opérateur » (« retirée » pour une pièce). Ce qu'elle a lu d'une pièce et ses liens restent : elle la rouvre encore en mots, mais ne peut plus la regarder de nouveau. La personne ne télécharge plus le fichier (410, `available` faux).
- **Rien d'autre ne change** : la rétention, la place par personne, l'oubli de toute la personne (qui efface tout, lignes comprises). La console ne supprime pas une ligne : ce qui a été envoyé ou reçu reste dit, seuls les octets partent.

*Pourquoi :* la rétention retirait déjà des fichiers en masse, mais l'opératrice ne pouvait retirer un document sensible, reçu ou envoyé par erreur, qu'en oubliant toute la personne ; et rien ne montrait d'un coup d'œil ce qu'elle avait envoyé à tout le monde (audit du 2026-11-05, C9-11, décision Q08).

*Révise 0106 (en partie : une pièce perd aussi ses octets quand un opérateur la retire, à l'unité).*

### 0206 — Les réglages d'un plugin vivent dans sa destination, derrière sa roue

- **Le modèle du Courrier vaut pour les autres plugins** (ADR 0173 : `SettingsPage.home`, la roue `Destination.gear`) : « Actif » et les comptes Teams sont dans Teams › Paramètres ; les réveils dans Réveils par API › Paramètres ; la connexion des serveurs MCP dans Ses outils › Paramètres des services, la roue de Venus d'ailleurs et des autres onglets de Ses outils ; les flux suivis, l'accès des appareils (leur jeton) et la transcription vocale dans Ses sens, derrière une roue « Réglages » qui les liste. Chaque page garde ses gardes, son audit et son journal, et s'enregistre toujours sous Réglages ; un formulaire refusé s'y remontre.
- **Un seul endroit.** Le fil d'Ariane, le menu allumé et la barre d'onglets disent la destination (« Échanges / Teams » au-dessus de « Paramètres », Teams allumé, ses onglets à côté de la roue allumée). Aucun lien du menu ne prend plus ces pages par `also`, et le menu Réglages n'a plus de lien Transcription.
- **La roue remplace le lien générique** vers les réglages : « Configurer le plugin » (Flux RSS, Appareils), « Leurs réglages » (Venus d'ailleurs) et le lien de réglages propre aux Réveils disparaissent ; un état vide dit où regarder. Le lien d'une tâche reste (déclarer un réveil, brancher un service, connecter une caméra, modifier un serveur) ; l'extension d'un compte Teams mène à ce compte (« Modifier ce compte », qui y ramène) : son compte et sa clé côte à côte.
- **Configuration des plugins reste la vue d'ensemble** : chaque ligne mène à ses réglages, nommés par leur destination (« Teams › Paramètres », « Ses sens › Flux suivis »), comme dans l'annuaire. Les anciennes adresses (Réglages › Plugins › Teams, Réveils par API, Outils extérieurs, Flux RSS, Appareils, Transcription) mènent aux nouvelles, leur requête gardée.
- Restent sous Réglages les réglages que plusieurs destinations partagent ou qu'aucune n'a : les modèles de texte et d'image, Carte et téléphone, Dépôts Git, les paramètres avancés de chaque faculté.

*Pourquoi :* le fil d'Ariane, le menu allumé et la barre d'onglets disaient trois endroits différents (« Réglages / Plugins », Échanges allumé, une barre « Flux RSS | Appareils connectés » sans rapport) ; régler un compte Teams ou un réveil demandait deux pages, dans deux menus. Le Courrier montrait que le modèle marche (audit du 2026-11-05, C7-05, décision Q11).

*Révise 0173 (en partie : son modèle vaut pour Teams, les réveils, les serveurs MCP et Ses sens), 0186 (en partie : ses comptes se règlent dans Teams › Paramètres).*

### 0210 — Les partages se voient tous dans la console, et un opérateur peut en retirer

- **Réglages › Droits › Partages** (un sous-onglet de la page, `app/handmade/rights.py`) : une ligne par partage — la ressource et sa sorte (boîte, compte Teams, service), son propriétaire, qui le reçoit (le lien de sa fiche), le niveau en mots. Tous ensemble, lus dans les réglages (`moi/shares.py::every_share`), comme ce que chaque personne lit sous « Partagé avec toi ». Un partage ne garde pas sa date : la ligne ne la dit pas.
- **Retirer** le partage d'une boîte ou d'un compte Teams : sur sa ligne, confirmé, audité (`console.droits.partage_retire` ; Système › Gestes audités : qui, la ressource et la personne). C'est l'écriture même de son propriétaire (`write_share` : relue puis réécrite sous `Settings.writing`, ses paramètres rejournalisés) : la personne ne le voit plus dans son espace. Un partage déjà parti n'écrit rien et n'audite rien.
- **L'audit porte sur le partage même** : `console.droits.partage_retire` et `moi.partage` ont pour objet `ressource_partagee`, `<sorte>:<clé>:<personne>`, jamais la ressource seule. Cette sorte n'est pas un sujet de la console : Gestes audités la dit en texte, sans lien. Sous `mail`, un sujet dont les fiches sont des messages, la ligne menait à une fiche qui n'existe pas (`partage`, lui, est le sujet d'un fichier envoyé). De même, cette page ne lie un objet que si sa fiche s'ouvre : le journal garde les `moi.partage` d'avant et tout objet retiré depuis.
- **Un service** renvoie à ses lignes d'accès, sur sa fiche : son partage y est une ligne (0192) et s'y retire déjà (0131).
- **Seul le propriétaire donne.** La console ne crée ni ne change aucun partage : ni personne à choisir, ni niveau. Les champs `shares` des réglages restent en lecture, et leur aide mène ici.

*Pourquoi :* un partage donne la lecture ou l'usage de la boîte d'une autre, la donnée la plus sensible pour la vie privée. L'opératrice ne pouvait répondre à « qui lit la boîte de qui ? » qu'en ouvrant chaque boîte, sur des clés brutes, et ne pouvait pas couper un partage abusif, alors que la console est l'espace super admin (audit du 2026-11-05, C9-04, décision Q07).

*Révise 0188 (en partie : un opérateur retire un partage qu'il n'a pas donné ; le donner reste au propriétaire).*

### 0216 — Facultés et plugins ne nomment pas les adresses de la console

- Une faculté ou un plugin dit ce qu'il vise par un lien (`Ref`) : une vue, la fiche d'un objet, une page de réglages (`Ref.settings`), la file « À valider » (`Ref.approvals`), un fichier (`Ref.download`). Seule la console, par `render.href`, en fait une adresse : le chemin d'une page, son préfixe et ses onglets n'existent que de son côté.
- **Où revenir** est un lien aussi : `Ref.back_to(page)`. La console l'écrit dans l'adresse (`retour`) ; `edit_server`, `edit_endpoint` et `edit_account` reçoivent un `Ref`, plus une adresse.
- **`Ref("local", …)`**, une adresse déjà construite, n'est que pour la console.
- **Une seule exception** : le lien des vues d'une app (`projects.share.app_link`), que Mika lit dans son prompt et donne à qui s'occupe d'elle. Un prompt ne passe pas par `render.href` : l'adresse fait partie de la phrase, dans sa voix, et un test la confronte à celle que la console écrit.
- **Deux gardes.** `tests/architecture/test_console_paths.py` refuse, dans `faculties/` et `plugins/`, toute chaîne qui commence par `/inspecteur` et tout `Ref("local", …)` ; la voix ne porte aucune autre adresse. `tests/protocol/test_console_links.py` suit chaque page nommée en toutes lettres : un nom se trompe comme une adresse.

*Pourquoi :* renommer une page de la console obligeait à éditer une vingtaine de fichiers de facultés et de plugins, sans garde, et l'une de ces adresses était déjà morte (audit du 2026-11-05, K11-01, K11-03).

### 0217 — Les anciennes adresses de la console vivent dans une seule table

- Une ancienne adresse se redirige depuis les tables de `inspector/pages/routes.py` : une page ou un onglet (`MOVED`, `MOVED_TABS`), un ancien enregistrement (`LEGACY_POSTS`), l'ancienne page d'un objet (`MOVED_VIEWS` : sa fiche, ou sa liste si l'adresse ne le nomme pas), un paramètre de liste qui ouvrait un objet (`MOVED_PARAMS` : sa fiche).
- Une faculté ou un plugin ne garde plus de vue pour d'anciens liens : « Un moyen de communication (ancienne page) » (`identity`, `?handle=`), « App forgée » (`forge`, `?app=`) et le paramètre `person` de Liens (`social`) sont devenus des redirections vers la fiche.
- Les filtres `handle` et `q` de Par personne (`transcript`, ADR 0181) restent : c'est une page vivante, qui les sert encore.
- Restent hors de ces tables, que la question Q03 ne nommait pas : le repli d'une ligne d'un onglet de fiche sur un paramètre de requête quand la fiche ne donne pas de clé (`?id=` des onglets d'un mail, plugin `email`, qu'un test vérifie ; `?person=` de Synthèse et Moyens de communication, `identity` ; `?handle=` de Fil, `transcript`), et l'ancienne page d'une personne (`app/handmade/person`), qui redirige déjà vers sa fiche. Les onglets d'un moyen de communication de `identity` (Verdict, Revendication, Preuves, Autres) n'ont plus ce repli.

*Pourquoi :* chaque refonte laissait sa trace dans le code du domaine pour servir d'anciens favoris ; que les liens d'avant mènent quelque part est l'affaire de la console (audit du 2026-11-05, K0-28, question Q03).

### 0218 — Une fiche dessinée lit ce que sa vue montre ; ce qu'elle lit à côté, elle le déclare

- Les fiches dessinées des objets vivent dans `app/handmade/subjects/`, un module par sorte d'objet (`server`, `handle`, `project` et `project_git`, `goal`, `wakeup`, `teams`, `mail`) et leurs aides dans `parts.py` ; la composition les reçoit ensemble (`subjects.OVERVIEWS`). La fiche d'une personne garde son paquet (`person/`).
- Ce que la vue de la faculté montre déjà, la fiche le lit dans ses blocs ou dans l'en-tête qu'elle déclare (`parts.faculty_head`), jamais par un second calcul : la fiche d'un but y lit sa sorte (une rêverie comprise), son autorité, son statut, sa priorité, sa prochaine séance et son envie.
- Ce que la vue ne dit pas sous la forme que la fiche dessine (un nombre qu'elle ne dit qu'en phrase, un formulaire qu'elle ne porte pas), la fiche peut le lire par les fonctions de la faculté, à condition de le déclarer : chaque nom qu'un module de `subjects/` importe d'une faculté hors de son `inspect` (ses mots et ses règles restent permis) est écrit, avec sa raison, dans la table `READS` de `tests/protocol/test_drawn_fiches.py`, et un import non déclaré fait échouer le test.
- Les fiches se reprennent une à une, en commençant par celle d'un but. Restent déclarées, à reprendre : la fiche d'un projet compte ses objectifs à côté de sa vue (qui les dit en phrase) et lit à côté les demandes qui attendent un accord ; celle d'un moyen de communication lit son verdict par la fonction de sa vue ; le dépôt git, l'adresse du distant (sa vue ne la donne qu'en lien).

*Pourquoi :* une fiche de but existait en deux calculs, celui de la faculté (servi au MCP et au repli) et celui du dessin, qui avaient déjà divergé (la prochaine séance) sans qu'aucun test ne le voie ; et les fiches se mêlaient aux onglets, sous des noms français ou mêlés (audit du 2026-11-05, K0-10, K11-08, question Q05).

*Révise 0177 (en partie : une fiche peut lire à côté ce que sa vue ne dit pas, en le déclarant, plutôt que de le faire toujours ajouter à la vue).*

### 0219 — Ce que la console et Outils disent encore mal : un onglet Comptes sans boîte, des badges qui disent quoi, des titres accordés

- **L'onglet Comptes d'une personne** paraît aussi quand elle n'a pas de boîte à elle mais a branché un service ou partage quelque chose, dans un sens ou dans l'autre : ses sous-onglets Services et Partages sont dessinés par sa fiche, qui le demande (`Overview.shows`, que `UI.subject_tabs` réunit aux onglets que les facultés montrent). Sans boîte, ni service, ni partage, Teams reste un onglet à lui.
- **Un onglet de la console rend son badge en couple** `(n, indice)`, comme une vue (`Builtin.badge`, lu par `badge_of`) : l'accueil dit ce que chaque ligne compte (« de Béa et Léa » pour les questions sans réponse, « en échec d'affilée : … » pour les processus, « hôte connecté à qui il manque quelque chose ») plutôt que « à regarder » ; quand le contrôle de santé de la même page dit la même panne, son constat reste (il dit depuis quand), le badge ne faisant que compter. Un nom suit son nombre, accordé (« 0 initiative », « 1 échec », « 2 brouillons d'elle à décider »), jamais « (s) ».
- **Une liste d'entrées déclare le nom de ses entrées, avec son article** (`Knob.noun` : « un fournisseur », « une autrice ») : une entrée neuve s'intitule « Ajouter un fournisseur » ; une liste qui ne le déclare pas garde « Fournisseur à ajouter ».
- **Le service du système a un titre et un but pour la personne**, écrits par la composition, qui joint le plugin au client MCP (`app/system_mcp.py`, `SHOWN` : « Le web ») ; un service de l'opératrice reste sans but dans Outils, son `purpose` étant la ligne du catalogue du modèle. **Le pourquoi d'une case d'app** redit la ligne de son app ou de son projet, lue par le plugin même (`forge.resource_allowance`), comme celui d'un service.
- Un geste audité sur une personne dit son nom même quand l'action ne déclare pas d'objet (supprimer un voyage depuis sa fiche) ; un jeton montré une seule fois se copie d'un bouton, qui retombe sur le texte sélectionné quand la console est servie en HTTP.

*Pourquoi :* une personne qui n'avait qu'un service ou des partages n'avait rien sur sa fiche, alors que les ADR 0188 et 0192 disent que la console les voit tous ; « 1 · Questions sans réponse · à regarder » ne disait pas pourquoi regarder ; le genre d'un nom ne se devine pas de son pluriel ; « Service « web » », sans but, ne disait rien à la personne du service dont elle se sert le plus (audit du 2026-11-05, C9-02, C1-10, C7-12, F4-12, C9-01, C9-05 et la décision Q21, repris par le lot LR1).

*Révise 0185 (en partie : l'onglet Comptes paraît aussi pour un service ou un partage), 0186 (en partie : de même, et Teams s'y joint alors), 0197 (en partie : une entrée neuve s'intitule « Ajouter un fournisseur »), 0209 (en partie : le service du système a un but écrit pour la personne, et une case d'app redit sa ligne).*

### 0225 — Un texte que la console affiche ne cite pas de numéro d'ADR

- Une description d'action, une note, l'aide d'un réglage, la description d'un droit ou d'une vue disent la règle en clair, sans « (ADR NNNN) » : le numéro est un renvoi de développeur, qui n'aide pas à décider d'un geste.
- Le renvoi reste dans les docstrings, les commentaires et la doc (`ARCHITECTURE.md`, `docs/console-carte.md`, `docs/decisions.md`).
- Une raison déjà gardée au journal ne se réécrit pas.
- Les textes des autres propriétaires suivent quand leur périmètre passe ; une garde viendra quand il n'en restera plus.

*Pourquoi :* l'audit en a retiré à quatre reprises, page par page (les descriptions de section, deux pages de réglages et d'Outils, les buts et les projets), sans que la règle soit écrite (audit du 2026-11-05, L05, C7-13, F4-08, puis K5-13 et la décision K5-Q2).

### 0230 — L'opératrice corrige sa mémoire, sans réécrire ce qu'elle a vécu

- **Une action de la console peut corriger un élément retenu**, posée sur sa carte, confirmée et auditée comme toute action (`runtime.operated`) : une promesse en cours **tenue** ou **abandonnée** (`memory.tenir`, `memory.abandonner` : `memory.promise_resolved`, `by` « opératrice », `contracts.memory.OPERATOR_BY`) ; une situation qui dure **finie** (`memory.finir` : `memory.situation_ended`, sans `by` : son audit dit qui l'a finie) ; un moment daté sans issue qui **a eu lieu, est annulé ou reporté** (`memory.issue` : `memory.resolved`, `by` « opératrice ») ; un souvenir ou une croyance qu'elle tient encore **démenti** (`memory.dementir` : `memory.retracted`, neuf). Les actions vivent dans `faculties/memory/actions.py`.
- **Rien ne réécrit ni n'efface un texte**, et rien n'écrit ce qu'elle croit : chaque correction est un événement ajouté au journal, les mêmes que ceux de la relecture sauf le démenti. Un élément démenti prend un statut d'avant (`retracted`, dans `FORMER_STATUSES`) : il sort de ce qu'elle sait (`memory_knowledge`), de son rappel et de l'index des vecteurs ; la liste le montre estompé, « démenti(e) », et son texte reste au journal. Ce qui le reprenait (un portrait, son récit) se réécrit sans le recopier, comme pour une source remplacée (`contracts.memory.withdrawals`, ADR 0082). Il ne se rétablit pas depuis la console.
- **Une correction n'est pas un moment de sa vie** : une issue posée par l'opératrice ne porte ni attente, ni annonceur, ni surprise, ni valence (ni émotion, ni calibration, ni leçon sur qui annonce, ni marque « voir venir ») ; abandonnée par l'opératrice, une promesse n'est pas « laissée filer » ; tenue, elle compte pour « tenir parole ». Le récit compte le changement, comme tout fait qu'elle sait désormais.
- Un moment se tranche une fois : une issue dite (« sans nouvelles » compris) ne se corrige pas. Ses pensées et son humeur restent sans prise depuis la console ; aucun oubli par élément : oublier reste l'affaire de toute une personne.

*Pourquoi :* l'espace super-admin doit pouvoir corriger une erreur de la relecture (un modèle qui extrait) ou une promesse qu'elle n'a pas vue tenue autrement qu'en oubliant toute la personne ; des événements qui existent presque tous déjà le font sans réécrire le journal (audit du 2026-11-05, C2-01, décision C2-Q1).

*Révise 0025 (en partie).*

### 0231 — La console écrit dans toute conversation Teams, et dit sous quel nom il part

- **La fiche d'une conversation Teams offre « Écrire dans cette conversation » sur tout compte** : à toi, à elle ou à une personne. C'est l'action de l'espace personnel (`teams.ecrire`), avec la mécanique de 0189 et 0199 : le message entre aussitôt dans la file de l'extension du compte, sans carte d'accord ni sa signature ; `teams.written` est journalisé dès qu'il est en file, et ses réponses qui attendaient un accord dans cette conversation sont refusées (« Répondu autrement »). Le geste est audité comme toute action de la console (`runtime.operated`), et le brouillon garde qui l'a écrit.
- **Il part sous le nom de la personne connectée à Teams dans le navigateur de ce compte** : le tien pour un compte à toi, sinon celui de son propriétaire (elle, ou la personne). Une note au-dessus du formulaire le dit par son nom, puis par celui que Teams lui donne quand l'extension l'a dit ; la confirmation du formulaire le redit (« sous le nom de la personne de ce compte »). C'est la console seule : l'espace personnel garde la règle de 0189 (le propriétaire, ou qui s'en sert par un partage).
- Teams coupé ou le compte décoché, rien ne part : la fiche ne l'offre pas et dit pourquoi, l'action le refuse.

*Pourquoi :* la console est l'espace super admin, on doit pouvoir y faire tout ce qui se fait ailleurs (le 5 novembre). Son courrier répond déjà depuis la boîte de n'importe qui, et un opérateur décide déjà dans la console des réponses de Mika qui partent sous le nom de la personne du compte (0186) : Teams n'a pas de raison de diverger. La confirmation qui nomme sous quel nom il part est le garde-fou (audit du 2026-11-05, C4-05, décision C4-Q1).

*Révise 0189 (en partie : un opérateur écrit aussi, depuis la console, dans le compte d'une autre personne).*

### 0232 — La console programme un rappel pour quelqu'un

- **« Programmer un rappel »** est dans la barre de titre de Buts et rappels (`goals.programmer`), sur sa page : quoi, quand (en heure locale), pour qui (vide : toi), urgent. C'est un but confié (`kind` rappel, `authority` « user », `source` « operator »), audité comme toute action de la console (`runtime.operated`).
- Son événement est celui que posent ses outils (`goal_remind`, `goal_plan_reminder`) : `goals.opened`, personnel, construit par une seule fonction de la faculté (`goals.tools.reminder`). Il se dit à l'heure dite là où la personne est alors ; pour toi, à défaut, là d'où tu l'as programmé. Il rejoint la colonne des rappels et se reprogramme comme un autre.
- Le formulaire est refusé champ par champ : quoi vide, personne inconnue, date illisible ou passée.
- La console ne lui confie pas d'exploration : c'est son initiative, dont l'envie s'use (0020), ou celle d'un réveil (0117). Confiée d'en haut, elle deviendrait une tâche.

*Pourquoi :* la console est l'espace super admin : elle doit pouvoir poser ce que Mika pose pour quelqu'un, sans passer par une conversation ni un réveil, comme Projets a « Créer un projet ». Un rappel est un service qu'on lui demande, à une date dite ; le geste s'ajoute sans contredire 0020 (un but a une autorité) ni 0030 (piloter par opérations auditées) (audit du 2026-11-05, C5-16, décision C5-Q1).

### 0234 — La console répare là où la panne se voit

- **« Reconstruire »** est sur chaque tranche corrompue, dans Anomalies et dans le sous-onglet de sa faculté de Diagnostic avancé : `Mind.rebuild([faculté])`, en ligne, sans arrêter les ajouts, puis la bascule — la reconstruction dont l'oubli d'un nom se sert déjà. Sa confirmation dit qu'elle relit tout le journal et qu'elle ne sert qu'une fois le réducteur corrigé (le serveur relancé sur ce code) : avec le même code, le rejeu lève au même événement. Le message dit le résultat — saine, ou encore corrompue au n° N — et les tranches qu'elle lit qui ne rejouent pas à l'identique. Une tranche saine ou volatile (qui ne se rejoue pas) est refusée. La commande `mika rebuild`, serveur arrêté, reste dite à côté.
- **« Réessayer maintenant »** est sur chaque processus en échec de Processus (« en échec », « a trébuché »), s'il n'est pas en cours : son recul est effacé et une passe demandée (`Scheduler.retry_now`) ; il repart à sa prochaine échéance, tout de suite s'il était dû. Un processus retenu pour une rafale ne se force pas, même s'il est aussi en échec : la garde est là pour ça. La fin de la retenue est gardée à part du recul (`held_until`) ; sa ligne dit pourquoi elle n'a pas le bouton.
- Les deux gestes sont des formulaires de la console (jeton, opérateur), audités `console.systeme.reconstruire` (sur la tranche, « échouée » si elle reste corrompue) et `console.systeme.reessayer` (sur le processus), comme Relancer un effet de la file de sortie.
- La sauvegarde reste à son unité : le serveur n'écrit pas le dossier des archives (`ReadWritePaths=/var/lib/mika`), et Stockage et sauvegardes dit la commande exacte. Pas de geste sur la quarantaine des projections : aucune n'est différée en service.

*Pourquoi :* la console est l'espace super admin : elle voyait la panne et renvoyait au terminal, avec une commande qui exigeait d'arrêter Mika alors que le moteur sait reconstruire en ligne ; sans ce geste, une tranche réparée par le code restait figée jusqu'à un arrêt du serveur, et un processus en panne attendait son recul, jusqu'à une heure, sans prise. Les deux gestes sont sûrs : la reconstruction en ligne sert déjà à l'oubli, et effacer un recul ne fait que devancer un essai que l'ordonnanceur ferait de toute façon (audit du 2026-11-05, C8-04, décision C8-Q1).

### 0237 — La console vit sous `/admin`

- La console est servie sous `/admin` (`inspector/render.PREFIX`), et non plus sous `/inspecteur` : elle règle les droits, les comptes et les réglages, ce n'est plus seulement un inspecteur. La console et l'app écrivent ses adresses par cette constante (`f"{PREFIX}/…"`). Seul un adaptateur, qui ne la voit pas (`adapters/web/protocol.py`), l'écrit en clair.
- L'ancienne adresse redirige : `/inspecteur` et tout ce qui est dessous mènent à la même page sous `/admin`, en 308 (la méthode, le corps et la requête suivent), depuis la table des anciennes adresses (`inspector/pages/routes.py`, ADR 0217). Les favoris et les liens d'avant mènent donc quelque part. Les clients (le web, `frontendv2`, Android) n'ouvrent plus que `/admin/…`.
- `/admin/souvenirs` est l'adresse courte de Mémoire › Souvenirs (`memoire/souvenirs`). La constellation suit le préfixe (`/admin/constellation`).
- Un mandataire relaie `/admin`, et `/inspecteur` le temps que les anciens liens s'éteignent (`deploy/README.md`).

*Pourquoi :* « inspecteur » nommait la console du début, qui regardait. Elle administre maintenant : une adresse qui dit ce qu'elle est, et une courte pour ses souvenirs, qu'on vient consulter.

*Révise 0025 (en partie).*

### 0241 — Les échanges d'une personne, une conversation à la fois, lus comme dans le chat

- L'onglet Échanges d'une fiche (et Fil, celui d'un moyen de communication) montre une conversation à la fois : par défaut « Leur conversation », le fil avec elle (tout ce qui n'est pas d'un fil de travail, salons compris) ; `?travail=<fil>` choisit un fil de travail du mode pro (ADR 0164), son seul contexte.
- Dès qu'il y a un fil de travail, une navigation à côté les liste (`transcript`, un `Workspace`) : le fil avec elle, puis chaque fil de travail sous son titre (sinon le début de son premier message, comme le chat), son nombre de messages, archivé à la fin. Un fil choisi dit sa description en tête. Sans fil de travail, pas de navigation.
- Les chiffres en tête et le compte de l'onglet comptent tous les messages. Les débuts de fil repliés en résumé ne se montrent qu'avec le fil avec elle, le seul qu'on résume.
- Ses réponses se lisent comme le chat les montre (`inspector/document.readable_markdown`, `markdown-it-py`) : en Markdown complet en mode pro (titres, listes, tableaux, code), gras et code ailleurs. La sortie repasse par l'assainisseur des mails : son HTML brut reste du texte, seuls les liens `http(s)` et `mailto` restent. Ce que la personne a écrit reste son texte.
- Un message du mode pro hors fil de travail dit « mode pro » (colonne `mode` de la faculté).

*Pourquoi :* l'onglet mêlait le fil ordinaire et les fils de travail sans dire d'où venait chaque message. Les réponses de travail, longues et en Markdown, s'y lisaient astérisques, dièses et barres de tableau compris.

*Révise 0181 (en partie : l'onglet Échanges d'une fiche).*

### 0281 — La fiche d'un projet rangée par ce qu'on y fait, et « à qui la main »

- **« À qui la main » est une règle pure** (`faculties/projects/todo.py`) : pour un projet et pour tous, ce qui attend une personne, dans l'ordre où s'en occuper — un accord (tout effet proposé dont le contexte est le projet, l'appel d'un service pendant son travail compris), un plan sans réponse, une demande d'aide, un projet arrêté par ses pannes ou un objectif bloqué, les tickets dont la main est au propriétaire, un point d'arrêt dit prêt, des relectures refusées deux fois, les éléments d'une liste de suivi à la charge de quelqu'un. Chaque entrée dit le projet, sa sorte, la référence de son texte, depuis quand, qui elle attend et le geste attendu (l'action de console, son onglet, la file « À valider » ou l'hôte). `for_person` la filtre pour une personne : son projet en entier ; celui d'un autre selon ce que ses lignes d'accès lui donnent hors de toute conversation (`links.given_to`), un accord et une reprise restant au propriétaire. Elle ne lit que l'état et le fait des effets en attente ; ses mots de console sont dans `inspect_todo.py`.
- **La fiche d'un projet suit ce qu'on y fait**, en une barre : *Où il en est* (ce qui t'attend en tête, ses chiffres, ses missions — les objectifs constants — et ses objectifs en cours, chacun en une ligne, ce qui vient ensuite, son plan ; puis, en sous-onglet, « Missions et objectifs » : l'ancien onglet Objectifs, réuni par `Overview.joined`), *Tickets*, *Suivi*, *Liens* (ce qu'il lit et ce que chaque lien donne, la vue de l'atelier, ce qu'il a demandé, ce qu'on lui a demandé, qui le lit), *Dépôt* (avec « Branches de travail » : la branche, la pull request, les vérifications et la relecture de chaque objectif), *Exécutions*, *Cadre* (en sous-onglets : ses réglages, ses outils et services, ses accès — l'ancien onglet Accès, réuni —, ses tickets et ses issues) ; Décisions techniques, Fichiers et Carnet sous « Plus ».
- **Rien ne disparaît** : chaque vue et chaque action d'avant a sa place, et `tests/protocol/test_project_fiche_tabs.py` en tient l'inventaire ; les adresses d'avant (`?onglet=objectifs`, `?onglet=acces`) mènent à leur section.
- **La page d'ensemble** (Projets › Ses projets) met en tête « À faire » pour tous les projets, dit pour chacun combien de choses t'attendent, et montre les liens entre projets : qui lit qui, ce que le lien donne, les demandes en cours.
- La vue de la faculté reste la source (la console en MCP, le repli) : ce que ces pages montrent de neuf est ajouté aux vues — ce qui attend, les missions et les objectifs en une ligne, la table des branches, les liens entre projets —, jamais relu à côté.

*Pourquoi :* les lots du chantier des chaînes de travail avaient posé leurs onglets, leurs lignes et leurs actions côte à côte, dans l'ordre où ils sont arrivés : pour savoir ce qu'un projet attendait de soi, il fallait ouvrir cinq onglets.

*Révise 0177 (en partie : les onglets de la fiche d'un projet), 0183 (en partie : l'onglet Dépôt montre les branches de travail), 0257 (en partie : ses liens ont leur onglet), 0270 (en partie : le réglage de la validation des tickets est dans Cadre). Révisée par 0286, 0290, 0297.*

### 0295 — Les cartes se refont sur le serveur, toutes les deux semaines

- Le serveur tient ses cartes à jour seul : `deploy/mika-cartes.service`, que `mika-cartes.timer` lance le 1er et le 15 du mois, la nuit, après la sauvegarde. Un passage manqué, machine éteinte, est rattrapé au démarrage.
- Dans l'ordre : les tuiles de la France (`mika carte extraire --zone france --zoom 15`) et leurs polices ; l'extrait OpenStreetMap du jour, téléchargé chez Geofabrik et gardé sous `cartes/france-latest.osm.pbf`, d'où se reconstruit l'index des lieux (`mika carte lieux`) ; les départements de DATAtourisme qui sont dus (`mika carte tourisme`).
- Chaque pièce neuve ne remplace l'ancienne qu'entière : tout se fait serveur en marche. Une étape des tuiles ou des données touristiques qui échoue laisse les anciennes et n'arrête pas le reste ; un index qui échoue fait échouer le passage, qu'on lit par `journalctl -u mika-cartes`.
- Il tourne à côté de Mika, au plus bas de la machine (`Nice`, entrées-sorties au repos) et borné en mémoire (`MemoryMax`) : il cède plutôt qu'elle. Le serveur porte donc l'extra `cartes` (pyosmium). Construire l'index sur un PC reste possible, pour un serveur trop juste.

*Pourquoi :* le serveur doit vivre seul. Les lieux, leurs horaires et les fiches vieillissent chaque jour dans OpenStreetMap, et l'index se construisait sur le PC, puis se copiait à la main.

*Révise 0193 (en partie : l'archive se refait d'elle-même), 0244 (en partie : l'index se construit sur le serveur).*

### 0297 — La fiche d'un projet dans la console est calquée sur l'écran Projets

- **La fiche d'un projet de la console reprend l'écran Projets du client web** (ADR 0291, la maquette validée) : son en-tête (son nom, son état en étiquettes, ses actions), puis ses onglets, dans cet ordre et sous ces noms — *Vue d'ensemble · Objectifs · Tickets · Code · Documentation · Activité · Dépendances · Listes* (seulement si le projet a une liste de suivi) *· Administration*. Plus de « Où il en est », de « Cadre » ni de « Plus ».
- **Les trois zones valent pour un onglet en liste et détail, et la liste est celle de l'onglet** — ses objectifs, ses tickets —, jamais celle des projets : à gauche la liste, au centre le contenu en volets, à droite un panneau (l'état, ce qui est lié avec son statut, les gestes). Une vue sans liste (le diagramme, ses listes de suivi) prend toute la largeur et ouvre le panneau au choix d'une ligne. Sur un écran moyen le panneau se replie en bande au-dessus du contenu ; sur un téléphone, la liste puis le détail (avec un retour), et le panneau est un volet « Infos ». On revient à la liste des projets par le fil d'Ariane, comme l'écran par « ‹ Projets ». Un choix d'élément est une adresse (la page se recharge sur lui) ; un volet est un sous-onglet.
- **La Vue d'ensemble est une grille de cartes sur toute la largeur, sans liste ni panneau**, comme sur l'écran : en tête, où il en est, et ce qui attend quelqu'un et à qui la main ; puis ses objectifs et leurs jalons en barres, son code (son dépôt distant, ses pull requests ouvertes avec leurs vérifications et leur relecture, son dernier commit), son prochain passage (son rythme, ses missions) ; puis ses tickets par étape, ses dépendances, ses dernières exécutions. Chaque carte mène à son onglet ; chaque fait s'y dit une fois. Son plan y est en carte, en tête, seulement quand il attend sa réponse ; sinon il se lit dans Objectifs. Ce que seul le portail dit (ses identifiants, ses plafonds, ses pannes) est dans Administration.
- **Objectifs** : la bascule Liste | Diagramme. En liste, une ligne serrée par objectif (un point à la couleur de son état, son texte, ses jalons en une barre, son dernier passage ; une mission dit sa cadence), par groupes, son filtre en pastilles ; l'objectif choisi montre ses jalons en étapes (comment on le vérifie, sa preuve, ses gestes), ses comptes rendus et sa relecture, et dans le panneau ce qui le dit fini, où il en est, sa branche et sa pull request avec leur statut, ce qui se gère. Le diagramme (« Avancement », « Dans le temps », en jours ou en semaines) est dessiné côté serveur, en SVG, à pixels fixes : la piste défile en largeur dans son cadre.
- **Tickets** : la liste (la recherche, les filtres — ceux qui attendent quelqu'un, ouverts, tous) ; le ticket choisi en volets — Description, Plan, Fil, Historique —, celui qui attend ouvert le premier ; dans le panneau son parcours en six étapes, « En bref », ce qui est lié (son objectif, sa pull request avec son statut, son issue). **Listes** : par statut ou en tableau, l'élément choisi dans le panneau avec son fil et son historique.
- **Tout geste de la fiche est une action déclarée**, dont la console prépare le formulaire pour l'objet choisi (son jeton, ce que la page fixe : l'objectif, le jalon, le ticket visés) ; il s'ouvre dans le contenu ou dans le panneau, jamais sur une page à part. Modifier ou retirer un jalon, modifier un ticket, confier un élément se font donc aussi dans la console. Le retour d'une action peut viser une section de la page (une ancre), pour revenir à ce qu'elle a changé.
- **Administration** porte ce que seul le portail règle, en sous-onglets, dans le gabarit du paramétrage : ses réglages, ses outils et services, ses lignes d'accès, ses tickets et ses issues, et « Sous le capot » (ses identifiants, ses plafonds et ses pannes, ce qui retient son exécution).
- **Code** : ses sous-onglets de l'écran — Fichiers, Commits, Pull requests, Branches, Issues, CI — sont des adresses (`?vue=`), chacun dans ses zones quand il a une liste et un détail ; Branches est un tableau sur toute la largeur qui ouvre son panneau au choix d'une ligne. Un fichier se lit à une branche, en chasse fixe et numéroté, un Markdown rendu ou en source ; un commit ou une pull request, leur diff unifié ou côte à côte ; une pull request en volets (Résumé, Commits, Fichiers, Échanges) avec son panneau (sa fusion, sa relecture, ses vérifications une à une, ses conflits, sa branche, ce qui lui est lié) ; une issue avec le ticket qu'elle propose, qu'on accepte ou écarte là. « Modifier », « répondre » et **« Fusionner »** sont les actions déclarées (`projects.pull_modifier`, `pull_commenter`, `fusionner`) : la fusion ouvre une confirmation qui dit ce qui part et nomme le commit de tête que la page a lu, et passe par la même règle et le même chemin que l'API (ADR 0288, 0292) ; elle ne s'offre que si l'action l'acceptera, la règle lue à l'instant de la page comme l'API la lit (une pull request toute fraîche attend ses vérifications) — sa branche a bougé, l'hôte dit ses vérifications pas finies : rien ne part, et la page de l'action le dit ; la console ne pose pas en plus la confirmation du navigateur. **Tout contenu de fichier, de diff ou de l'hôte est du texte brut** ; ce qui vient d'ailleurs se dit ; un Markdown du dépôt se rend sans image chargée ni lien qui s'ouvre. **L'hôte se lit par une lecture gardée et bornée** (`inspect_code.hosted` : gardée deux minutes, une erreur trente secondes, trente par minute au plus pour la console ; « relire » la refait une fois, et recharger la page ensuite ne la refait plus) : une page ne le joint pas à chaque affichage. L'atelier face au distant (pousser, récupérer, ses échanges, ses réglages) garde le dessin de l'onglet Dépôt d'avant, sous `vue=distant`, où mène le dépôt distant au bout de la barre ; l'ancien onglet Fichiers (l'arbre de travail) mène à Code › Fichiers, et « Déposer un fichier » y est.
- **Documentation** : ses sous-onglets de l'écran — Pages, Images, Décisions — sont des adresses (`?vue=`). Une page est rendue par le moteur (`project_docs.doc_html`) : ses titres gardent leur ordre, un cran plus bas que le titre de la page, ses tableaux sont des grilles ; **une image ne se montre que si elle est dans sa documentation**, servie par la console (`/admin/image/project/<n>`, le document que déclare la faculté, une image et rien d'autre ; son adresse change avec elle, le navigateur la garde), une image d'ailleurs n'est que son texte ; **seul un lien vers une autre page de l'espace s'ouvre**, dans la console, aucun autre ; aucun script. Son panneau : son sommaire, qui l'a écrite et par où, ses versions. **L'éditeur est écrit pour la console** (`static/handmade/doc_editor.js`) sur un champ ordinaire, qui suffit sans lui : une barre d'outils qui agit sur la sélection, « Écrire | Aperçu | Les deux » — l'aperçu rendu par le moteur (`/admin/apercu/project/<n>`, `Overview.preview`), comme la page le sera —, l'insertion d'une image de l'espace, ce qui n'est pas enregistré. Pas Milkdown Crepe : la console n'a pas de chaîne de construction, sa CSP refuse les styles qu'il pose en ligne, et il pèserait plus d'un mégaoctet pour une page de console ; et une seule façon de rendre une page. **Enregistrer passe par l'action déclarée** (`projects.doc_ecrire`), comme l'API : elle nomme la version lue ; le retour dit la version lue, et la page sait par le message de l'action (`UI.peek_flash`) si l'enregistrement est passé. Refusé, l'éditeur revient avec le texte tapé (gardé par le navigateur le temps de l'envoi) ; **ce n'est un conflit que si la page a bougé** : il le dit avec les mots du moteur, montre la version actuelle et repart d'elle ; une page créée sur un chemin pris dit qu'elle existe déjà. Le texte revenu n'est pas enregistré : quitter la page le demande. Recharger la page après coup n'est ni un refus ni un conflit (le message de l'action a été montré). Revenir à une version, créer, renommer, supprimer une page, téléverser une image (son fichier par `_fichier`, que la console passe à l'action), la retirer : les actions déclarées. **Décisions** : la liste et le détail d'une décision technique (le choix, le contexte, la raison ; les options écartées ; ce qu'elle remplace, ce qui l'a remplacée, l'objectif) ; la consigner, la modifier, la remplacer, la retirer, la remettre en vigueur.
- **Activité** : Fil, Exécutions, Carnet. **Le fil** est lu par la même fonction que l'API (`faculties/projects/feed.py`), la console voit tout et nomme chacun ; ses filtres (une sorte, un objectif), sa pagination par curseur ; chaque ligne mène à ce qu'elle nomme ; son panneau : trente jours en barres (du SVG dessiné par le serveur), le prochain passage, qui a fait quoi. **Une exécution** dans les trois zones : son compte rendu, ce qu'elle a fait pas à pas (sa trace, `feed.steps`), son verdict et sa preuve, son commit, ce qu'elle a demandé — et **les onglets de son épisode** (prompt, outils, appels, décision), dessinés par la page d'un épisode, un à la fois. **Le carnet** : ses notes en cartes, ses consignes, ce qu'on en a fait, ce qui sort, chacun avec sa pagination.
- **Dépendances** : Schéma, Demandes. Le schéma met le projet au centre, ce qu'il lit d'un côté, ce qui le lit de l'autre ; un lien choisi ouvre le panneau — son pourquoi, ce qu'il donne, le commit que montre sa vue, ses demandes et leur mode. L'ajouter avec son pourquoi, changer ce mot, le mode direct, le retirer : l'action `projects.liens`, tout son état posé par la page, le mot en valeurs fixées, comme l'API ; avec l'état que la page a lu (`seen`, `actions.links_seen`) : s'il a bougé depuis (un autre onglet), l'action refuse plutôt que de défaire ce qui a changé — l'API, qui n'envoie que ce qui change, n'en pose pas. Les demandes envoyées et reçues, chacune avec son ticket.
- **Une adresse d'avant mène à ce qui l'a remplacée sans exécuter sa vue** (`Overview.moved`) : `?onglet=fichiers` à Code, `decisions` à Documentation › Décisions, `carnet` à Activité › Carnet ; seul `acces` reste réuni sous Administration. **L'atelier face au distant** ne garde que ce qui lui est propre — pousser, récupérer, ce qui n'est pas enregistré, ce que le distant a de plus, les échanges, les réglages — : ses commits, ses branches, ses issues et ses pull requests sont les sous-onglets de Code. **La page d'une pull request dit ce que le moteur dirait** : sa propre lecture de l'hôte (sa tête, ses conflits, ses vérifications sur ce commit, `merge.checks_block`, la règle même de l'action) retient « Fusionner ». Un diff côte à côte défile dans son cadre, sans couper une ligne.
- **Là où les règles de la console (0176) et la maquette validée se contredisent, la maquette l'emporte pour cette fiche** : des sous-onglets en barre plutôt qu'en colonne, des cartes plutôt qu'une bande de chiffres, pas d'onglets sous « Plus », des états en pastilles. Restent ceux de la console : ses jetons (couleurs, arrondis, Inter), sa barre du haut, le français, sa CSP stricte.
- **Une seule source pour ce qu'un projet montre** : `faculties/projects/glance.py`, pur — l'avancement de ses objectifs, ses tickets par étape, l'état d'un jalon, son prochain passage, sa dernière activité — et `faculties/projects/diagram.py`, pur aussi — les lignes du diagramme et leurs vraies dates —, et pour son code `faculties/projects/inspect_code.py` — où en est une pull request, l'objectif d'une branche ou d'un commit, le ticket d'une issue, les mots de ce qui ne s'affiche pas, un diff mis en texte et relu —, que l'API par personne lit aussi (`app/me/project_code.py`) ; pour son activité `faculties/projects/feed.py` — ce que chaque événement du journal donne au fil, les pas d'une exécution —, que lit aussi `app/me/project_activity.py`. L'API par personne et la fiche de la console les lisent tous deux, comme le parcours d'un ticket (`tickets.journey`) et son registre (`tracker`) ; la console, elle, voit tout. Ce qui attend reste `todo.py` (0281). Les vues de la faculté gardent leurs blocs (la console en MCP, le repli).
- Une vue d'ensemble peut tenir un onglet hors de la barre tant qu'on n'y est pas (`Overview.hidden`) : son adresse marche toujours.

*Pourquoi :* le propriétaire a validé l'écran Projets du client web au troisième tour, puis a trouvé dans la console l'ancienne fiche — deux dessins pour le même objet, et le moins bon là où il administre.

*Révise 0176 (en partie : la vue d'un objet, les sous-onglets et les étiquettes, pour cette fiche), 0177 (en partie : les onglets de la fiche d'un projet), 0281 (en partie : l'ordre et les noms de ses onglets, « Où il en est », « Cadre », « Plus »), 0282 (en partie : ce que l'API calculait pour la carte et la fiche d'un projet se lit dans `glance.py`), 0183 (en partie : l'onglet Dépôt devient « l'atelier face au distant », une sous-vue de Code), 0288 (en partie : la console fusionne aussi depuis la fiche d'une pull request ; ce que l'API calculait seule du code d'un projet se lit dans `inspect_code.py`), 0289 (en partie : la documentation d'un projet s'écrit aussi depuis la console, par les mêmes actions), 0290 (en partie : ce que l'API calculait seule du fil d'un projet se lit dans `feed.py`).*

### 0310 — `app` rangé par domaine : une fiche et un dossier chacun

- **Un domaine, un dossier.** Ce que la couche `app` sait d'un domaine (le courrier, Teams, l'agenda, l'annuaire, la carte, ses outils, la Forge, ses projets, les réveils, ses sens, le téléphone) vit dans `app/domains/<nom>/` : ses réglages, son câblage, son module de `/api/moi`, sa part du direct, ses pages de console, sa commande. Une page qui croise les domaines (qui peut quoi, les partages, À valider, la fiche d'une personne, le port d'entrée, Système) reste au cadre et lit les fiches : chaque domaine y inscrit sa part, sous une forme écrite pour cette page (`app/domains/domain.py`).
- **Une fiche écrite à la main** (`Domain`, `app/domains/domain.py`) dit ce qu'il apporte ; `app/domains/__init__.py` les liste (`DOMAINS`), dans un ordre voulu. Une fiche n'importe rien : elle nomme les modules de ses parts (son API, sa part du direct, sa part de la console, son aperçu), que le cadre importe au moment d'assembler et où il lit un nom convenu ; le registre est donc une feuille de l'arbre des imports, que tout module d'`app` peut lire sans tourner en rond. Le cadre (`server.py`, `schema.py`, `backup.py`, `me/`, `handmade/pages.py`, `console.py`, `cli/`) parcourt cette liste et ne nomme aucun domaine ; un domaine n'en nomme un autre que s'il le déclare (`Domain.needs`). `tests/architecture/test_frame_names_no_domain.py` le garde, sans table d'excuses : seul ce que le cadre nomme exprès y est dit, avec sa raison. Rien n'est découvert : ni balayage de dossiers, ni points d'entrée.
- **Rien n'est généré.** Une fiche inscrit des pages, elle n'en dessine aucune : chaque page de la console garde son gabarit et sa feuille (ADR 0121, 0177), chaque écran des clients le sien. Les gabarits et les feuilles d'un domaine vivent dans son dossier (`console/templates/`, `console/static/`), sous les mêmes noms et aux mêmes adresses ; ceux du cadre restent dans l'inspecteur, qui reçoit les dossiers des domaines de la composition et n'en nomme aucun. Un même nom n'existe que dans un dossier.
- **`Settings` est une porte** : lire, écrire en le disant (`_put`), sceller. Les réglages d'un domaine sont une classe de son dossier, qui n'écrit que par cette porte ; ceux qui n'ont pas de domaine (les modèles, sa persona, ses droits, ses autrices) restent dans `app/settings.py`.
- **Restent au centre, exprès** : la liste des facultés, les lots d'outils et l'ordre de son prompt (`app/composition.py`, ADR 0151) ; l'ordre de chaque liste où il se voit — le menu de la console, la page des plugins, les sortes de partage, les canaux —, que le cadre garde en noms et vérifie contre les fiches ; les sujets du direct (`ports/changes.py`, le contrat) ; un dossier de migrations par base (`app/migrations/<base>/`) ; et la vie fictive de l'aperçu de la console (`app/preview/__init__.py`), un scénario écrit à la main où les domaines se mêlent, auquel un domaine neuf ajoute sa part par sa fiche.

*Pourquoi :* l'agenda (ADR 0309) a demandé de retoucher dix-sept fichiers partagés, et chaque domaine de sa taille refaisait le même tour — ces fichiers sont aussi ceux où deux sessions se heurtent.

*Révise 0177 (en partie : le module qui déclare les onglets d'un domaine, leurs gabarits et leur feuille vivent dans son dossier).*

## Ce que les sondes et les audits ont fixé

### 0043 — Ce qu'une semaine avec un vrai modèle a montré

- Le journal de sa journée a deux versions : l'intime, et une partageable où personne d'autre n'apparaît (ADR 0053). Ce qui n'y est pas ne peut pas s'ébruiter.
- Un secret ne laisse pas deviner qu'il existe. Ce qui est privé sans être secret garde la ligne vague, sans mentir (« ce n'est pas à moi d'en parler »).
- Un message lu en retard le dit dans son repère ; au réveil, elle répond comme qui le lit tard, pas comme si le message l'avait réveillée.
- « CE QUE TU TE RÉPÈTES » lui fait remarquer ses tics (même ouverture, bonjour redit) ; rien n'est interdit.
- Une rêverie qui ne donne rien se dissipe, sans frustration ni « je bloque ». « Alors, cet entretien ? » (`others.follow_up`) ne porte jamais sur ce qu'un tiers a raconté.

*Pourquoi :* le vrai modèle a montré des secrets qui fuyaient par le journal, une discrétion qui tournait au mensonge ou à l'aveu, une vie intérieure mécanique.

*Révise 0034 (en partie). Révisée par 0048, 0053, 0054.*

### 0048 — Les noms dont on lui a parlé, les au revoir, et la sonde

- Un nom se relie, il ne se devine pas : seul un opérateur relie un nom entendu à une personne (`identity.name_bound`) ; les noms reliés sont des alias qu'emporte l'oubli.
- Veto `agency.farewell` : quelques heures après un au revoir, aucune initiative ordinaire vers la personne, même connectée ; ce qui est dû ou prévient passe.
- La sonde (`mika sim sonde`) vit au modèle configuré, sans écrire dans le dossier de données. Elle refuse Claude Code, dont le relais d'outils ne vit que dans le serveur.
- Ce qu'elle a dit n'est pas ce qu'on lui a appris : une croyance dont les seules sources sont ses propres lignes est écartée.
- Les jetons de l'extraction (« [P1] ») n'atteignent ni souvenir, ni rêve, ni journal.

*Pourquoi :* une personne dont on lui avait parlé restait distincte d'elle une fois arrivée, et un au revoir n'arrêtait pas les initiatives.

*Révise 0043 (en partie), 0046 (en partie). Révisée par 0054, 0055.*

### 0054 — La seconde semaine de la sonde, et ce qu'elle a montré de la conversation

- Ses bonjours sont les siens : simple à une inconnue, ses petits mots de persona à qui elle connaît. Jamais une formule tendue au modèle : elle se recopie.
- Une réponse qui redit mot pour mot son dernier message ne part pas (abstention) ; un petit mot peut se redire.
- En salon, hors secret, elle ne prétend pas ne rien savoir : ce qui s'est dit en privé ne se raconte pas ici. Un secret ne laisse rien deviner.
- Face à des réponses de quelques mots, elle fait court, sans question (`faculties/others/faculty.py::curt_run` ; sa règle : `contracts/others.py::few_words`). Après une abstention ou une panne, chaque hésitation envers la personne double (`agency.HESITATING`).
- Un fournisseur qui ne sait pas différer (Ollama, compatibles OpenAI) reçoit ses outils en main ; un outil qui réussit peut clore la boucle (`ToolSpec.ends_loop`).

*Pourquoi :* une seconde semaine (deuil, anniversaire, surnom, salon) a montré des tics, des mensonges par ignorance en salon et des appels inutiles.

*Révise 0024 (en partie), 0033 (en partie), 0043 (en partie), 0048 (en partie), 0052 (en partie). Révisée par 0055.*

### 0102 — Les correctifs de l'audit du 12 octobre (émotions et mémoire)

- Pendant qu'elle parle à quelqu'un, l'écran montre son visage envers lui (`affect.FACE`), pas sa balise brute ; un murmure ou une parole sans destinataire garde la balise.
- Un message qui la tire du sommeil (`body.roused`, une parole visible) réveille aussi son humeur ; une nuit coupée n'allège jamais plus qu'une nuit entière.
- Le doute d'une croyance contestée ne nomme qu'un témoin que l'audience entend, sinon « quelqu'un » ; ce que la personne ressent (`felt`) ne se dit que là où son témoignage s'entend.
- Un élément devenu confidence par un sujet délicat fait taire ce qui en dérive (pensée, rêve, journal, récit, portrait) ; oublier quelqu'un emporte aussi ses promesses et ce qui l'a touchée de grave.
- En salon, la relecture ne voit que les promesses que ce salon a entendues ; une discrétion demandée ferme un souvenir sans le faire durer.

*Pourquoi :* l'écran, l'humeur ou la mémoire trahissaient ce qu'elle laisse voir ou ce qu'on lui avait confié.

*Révise 0100 (en partie). Révisée par 0107.*

### 0135 — Les correctifs de l'audit du 26 octobre (d'équerre, hors CI)

Un audit complet en lecture seule (`docs/audit-2026-10-26.md`) ; tout ce qui suit a été corrigé dans le même lot, la CI et le verrou de dépendances mis à part (choix de l'utilisateur).

- **Le schéma.** Une base est complétée (colonnes, index absents) ou refusée en le nommant (`SchemaDrift`) : jamais marquée à jour sans l'être — `create_all` ne touche pas une table qui existe, et `data/v2` l'avait payé.
- **Le journal.** Un trou de séquence est une anomalie dite : la relecture le voit (`BootReport.gaps`), la santé passe `ko`, `replay --verify` échoue et liste les trous. Les lectures du magasin qui retiennent la boucle d'événements sont mesurées (50 ms) et montrées (200 ms : `degraded`). Une projection T0 se reconstruit par lots, la version écrite en dernier. Le dédoublonnage d'un lot fait une requête.
- **L'oubli atteint toutes les tranches.** `kernel.subject_forgotten` est réduit par toute faculté qui range quelque chose sous la clé d'une personne (identité, posture, ce qu'elle sent des gens, attentes, confidences faites, hésitations, liens du graphe) : ce qu'elle a appris d'elle et ressenti pour elle s'en va ; son adresse reste une adresse, déliée, et son lien reste (proximité, rythme, dernier message : un compte qui existe garde son fil, et son profil se montre oublié dans la console). **Une inconnue de passage** (jamais reliée ni authentifiée, dont elle n'est pas proche) silencieuse depuis `stranger_ttl_days` (90 jours) s'en va entièrement, lien compris (`identity.expired`, une fois par jour) ; une amie, un compte, une personne connue de nom, jamais.
- **Un réglage à sa borne ne casse rien** : `goals.abandon_below` ≥ 0,01 et l'instant d'usure sans division ; le tirage d'une relance est daté, les plus récents gardés (une carte triée par clé n'est pas une file).
- **Le premier compte.** Depuis une autre machine que celle du serveur, la page de connexion (web et console) exige le code de premier démarrage que `serve` tire et écrit au journal tant qu'aucun compte n'existe : le premier arrivé sur le réseau ne devient pas opérateur. Sur la machine du serveur, rien ne change.
- **La sécurité des bords.** Un identifiant SQL venu d'une app (un nom de table) passe par `identifier_preparer.quote`, et `MULTI_STATEMENTS` ne s'active jamais sur PyMySQL. Toute route HTTP ordinaire borne son corps à 64 Kio (413) par un lecteur commun ; les portes des services gardent leurs plafonds. Le réseau libre de la Forge refuse aussi les adresses propres de l'hôte (v4 et v6, relues toutes les 5 min) et tout port où le serveur écoute. Les cages posent `--unshare-user --disable-userns` (pas d'espace d'utilisateur imbriqué, et sans userns non privilégié rien ne se lance : pas de repli). Un jeton qu'on ne fait que vérifier (appareils, console MCP) est gardé en empreinte SHA-256, jamais scellé ; un scellé d'avant est converti à l'ouverture. À la restauration, la cible d'un lien symbolique reste dans le dossier, sauf sous `ateliers/` et `mcp/` où le serveur ne suit jamais un lien. `secret.key` naît par `O_CREAT|O_EXCL` en 0600 ; `forge/`, `ateliers/`, `mcp/` sont en 0700. Les journaux masquent aussi `Basic`, les jetons `mw_`/`mtk_`/`mwk_`/`mlp_`, `X-Gitlab-Token` et `MYSQL_PWD=`. Sans `--behind-proxy`, la première requête portant un en-tête de mandataire est signalée une fois. Les appareils de `/api/perceptions` sont étranglés comme les connexions.
- **La couche modèle.** Le délai d'un appel est celui de l'épisode qui porte la requête (`LLMRequest.deadline_s`, borné par ce qui reste devant l'épisode) ; le délai par voie reste celui des processus ; un appel dont l'épisode n'a plus de temps n'est pas tenté (issue `expired`, pas « timeout »). Un fournisseur dit son plafond de sortie effectif (`output_tokens`) : aucun rejeu après coupure si ce plafond ne monte pas, et le budget réserve la sortie dessus, jamais plus de la moitié du contexte déclaré ; Claude Code le dit aussi (1 024 au moins, 16 384 avec des outils). Un fournisseur Claude sans contexte déclaré en reçoit 40 000, et un contexte qui ne laisse pas la moitié à son prompt est dit au démarrage. Opus, Sonnet, Haiku 5.x, Fable et Mythos réfléchissent d'emblée : plancher de 16 384 jetons de sortie même sans `effort`, et jamais de température ; Haiku 5.5 à 0,10 $/0,50 $ le million. Un refus du modèle (`stop="refusal"`, sa catégorie dans `stop_detail`) règle l'épisode en `failed` « refus du modèle », jamais en abstention ; les replis côté serveur restent à décider. Le tour de clôture d'une boucle part `tool_choice="none"` (l'API Claude refuse des `tool_use` orphelins sans leurs outils ; Ollama ne les envoie pas ; une session Claude Code vivante garde les siens). Le résultat d'un outil venu d'ailleurs entre dans le fil **cité** (`cited`, borné par la politique de l'épisode : `EpisodePolicy.outside_chars`, 24 000 caractères, 120 000 en mode pro où un service rend des fichiers entiers), son erreur neutralisée ; la trace garde le brut et dit la coupe (`ToolRecord.cut`). Dans une ligne citée, seule une suite de tirets qui ouvre ou ferme la ligne est désamorcée : un tableau, un JSON restent relisibles. Une récriture (seconde passe, autrice d'un brouillon) qui perd un nombre ou un lien du premier jet est écartée — les nombres en lettres, les ordinaux, les mois, « pour cent » et « degrés » du texte récrit comptent comme des chiffres (`runtime/facts.py`) : « à seize heures » garde « 16 h ». Chaque trace garde l'entrée estimée à côté de l'entrée réelle (`estimated_input_tokens` ; chez un fournisseur qui fait plusieurs appels pour une réponse, la plus grande entrée d'un seul, `LLMResponse.prompt_tokens`), un avertissement par fournisseur et par heure hors [0,7 ; 1,4], sans recalage automatique. Ollama reçoit `num_ctx`, et `max_reply_tokens` ne plafonne que les rôles voix. Claude Code : `system.txt` ne reçoit que la zone stable, le volatile (où voyage ce qui vient d'ailleurs) part encadré dans le tour utilisateur ; une sortie coupée n'est un appel d'outil coupé que si un appel était annoncé. `cited()` coupe à une frontière ; `closing()` lit toutes les graphies d'`EN_FACE` et ne tronque qu'une suite sans phrase ; jamais un dernier tour utilisateur vide (`llm.thread.silence`) ; une extraction dont `confidentiel` est mal typé garde ce qui était valide.
- **Ce que l'audit croyait et qui tenait déjà** : le rejeu d'un réveil signé se reconnaît par la clé d'idempotence du journal, pas par l'état du plugin (pas d'anneau à part) ; `datetime.combine(…, tzinfo=tz)` puis `instant()` donne le même instant que `next_local` aux changements d'heure (rien à changer).
- **L'exploitation.** `mika.service` borne la mémoire et les tâches (`MemoryHigh`, `MemoryMax`, `OOMPolicy=continue`, `TasksMax`) ; un modèle de plongements qui n'est pas celui réglé au banc est dit au démarrage ; les sauvegardes se copient hors de la machine, chiffrées, et `MIKA_SECRET_KEY` est préféré à un `secret.key` archivé ; l'extra `llm` n'installe plus de paquets qu'on n'importe pas.
- **Les tests.** Les montages de protocole en horloge réelle posent `reply_wait=None` (la nuit, sa réponse à un inconnu attendait son réveil : les quatre échecs nocturnes) ; les cages se prouvent contre une oreille locale de l'hôte, pas contre Internet ; des propriétés (`FrozenDict`, `canonical_json`, `tighten`, `_marks`) gardent le noyau ; un module qui nomme les tables de la mémoire pour les étiqueter n'est pas un lecteur.

*Pourquoi :* un audit de relecture (noyau, persistance, sécurité, couche modèle, facultés, tests) a trouvé une base marquée à jour sans l'être, des tranches qui grossissaient avec chaque correspondant vu une fois, un premier compte ouvert au premier arrivé, et une dizaine de bords sans borne.

*Révise 0101 (en partie : la migration vérifie), 0024 et 0045 (en partie : l'oubli atteint les tranches), 0059 (en partie : les inconnues de passage expirent).*

*Révisée par 0267.*

### 0266 — Les correctifs de texte de l'audit des contextes du 20 novembre

- **Une phrase assemblée se lit.** Ce qu'elle pourrait se fabriquer se dit entre parenthèses, ses moyens séparés par « ; ou » (`runtime.tools.acting_means`, `means_forge`, `means_or`) : « — … — que tu dis ensuite à qui l'attend ou un projet à toi — » ne se lisait pas.
- **Son humeur ne s'oppose pas à elle-même.** « Normalement tu es plutôt {usual} ; en ce moment, ton humeur générale est… » (`affect.mood_line.caused`), sans « alors que » : « à peine soulagée, alors que normalement tu es plutôt contente » opposait deux humeurs qui ne s'opposent pas. L'habitude vient d'abord, pour que la cause suive ce qu'elle ressent.
- **Une note d'elle se dit à elle en entier, ou reste la sienne.** Dans « CE QUI VOUS LIE », `to_you` ne convertit plus une note qui garderait un « je » après coup : « moi le poney » devenait « toi le poney » dans une ligne qui disait ensuite « je l'ai faite ».
- **Une rêverie reprise ne se dit qu'une fois.** Dans « CE QUE TU AS EN TRAIN », deux rêveries finies du même titre font une ligne, la plus récente.
- **Un lot vide ne s'offre pas.** Sans flux suivi, `rss_list` et `rss_read` ne s'offrent pas et le catalogue ne les annonce pas (`needs="feeds"`).
- **Ce qui vient d'un mail part cité, au tri aussi.** L'expéditeur et l'objet sont rendus inertes, le corps cité (`ports.preprocess.inert`, `cite`), pour le tri du courrier comme pour celui de Teams.

*Pourquoi :* le prompt réel du 19 novembre 2026 portait une phrase cassée par l'assemblage, une note à moitié convertie, deux fois la même rêverie, une humeur opposée à elle-même et un lot de flux vide — son premier appel y est allé pour rien ; et le mail partait brut au tri, seul endroit où ce qui vient d'un mail n'était ni inerte ni cité.

*Révise 0198 (en partie : le tri cite aussi).*

### 0314 — Un nom privé ne se lit pas d'un autre module

- **Un nom qui commence par un soulignement est à son module.** Dans `src/mika`, aucun module n'importe le `_nom` d'un autre (`from x import _nom`) ni ne le lit par son module (`x._nom`). Ce qu'un autre module lit porte un nom public, là où il est défini.
- **Une aide que plusieurs modules partagent a un module à elle**, nommé d'après ce qu'elle sert, plutôt qu'un nom public de plus dans un gros module : `inspect_common.py`, `tool_common.py` et `capability_common.py` pour les projets, `app/domains/projects/api/reach.py` pour leur API, `adapters/maps/geo.py` pour la carte.
- **Un nom rendu public se choisit pour ses lecteurs** : il dit ce que la chose rend (`opened_project`, `texts_of`, `acting_person`) et ne heurte aucune de leurs variables locales.
- **Les tests lisent ce qu'ils veulent** : la règle vaut pour `src/mika`. Un nom à double soulignement et un sous-module ne sont pas des noms privés.
- **La garde** (`tests/architecture/test_private_names_stay_in_their_module.py`) le lit par l'AST, et n'excuse rien.

*Pourquoi :* l'audit d'organisation du 26 novembre a compté 114 noms privés lus d'un module à l'autre, dont 38 dans les seuls projets — une couche commune qui n'existait pas comme telle. Une retouche de `_author` ou de `_opened` changeait en silence quatre modules de l'API des projets et un point MCP, et un module neuf devait importer les privés d'un fichier de 1 500 lignes.
