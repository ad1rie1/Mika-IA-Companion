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
*Révise…* s'il y a lieu ; puis « Révisée par NNNN » sur les entrées qu'elle change, et son numéro dans la carte. En
cas de désaccord avec le code, le code fait foi : corriger l'entrée, ou en ajouter une.

## La carte

| Thème | Décisions |
|---|---|
| Le noyau : journal, arbitrage, pipeline | 0001, 0002, 0003, 0006, 0007, 0008, 0009, 0014, 0015, 0021, 0040, 0059, 0149, 0151 |
| Le stockage | 0004, 0101 |
| Sa mémoire et ce qu'elle sait | 0010, 0011, 0034, 0046, 0052, 0055, 0074, 0076, 0078, 0079, 0080, 0081, 0082, 0083, 0084, 0085, 0086, 0087, 0091, 0099, 0109, 0110, 0111, 0153 |
| Identité et divulgation | 0012, 0035, 0075, 0092, 0133, 0134, 0148 |
| Sa vie intérieure : affect, corps, besoins, liens, initiatives | 0013, 0016, 0017, 0018, 0019, 0028, 0032, 0033, 0036, 0044, 0047, 0053, 0058, 0088, 0089, 0090, 0093, 0094, 0095, 0096, 0097, 0098, 0100, 0107, 0118, 0137, 0150 |
| Buts, projets, Forge et atelier | 0005, 0020, 0023, 0030, 0031, 0039, 0104, 0105, 0143, 0144, 0145 |
| Les sens et les plugins | 0022, 0027, 0037, 0038, 0061, 0063, 0064, 0066, 0068, 0069, 0106, 0117, 0119, 0120, 0128, 0129, 0130, 0131, 0132, 0147 |
| Les fournisseurs de modèles | 0026, 0072, 0073, 0127, 0136, 0142 |
| Sa voix, sa persona, la genèse | 0070, 0071, 0112, 0114, 0115, 0124, 0138, 0139, 0140, 0141, 0146, 0152, 0154 |
| Les clients, le fil, le monde | 0041, 0049, 0050, 0051, 0056, 0060, 0062, 0065, 0067, 0077, 0108, 0113, 0116 |
| La console et l'exploitation | 0024, 0025, 0029, 0042, 0045, 0057, 0103, 0121, 0122, 0123, 0125, 0126 |
| Ce que les sondes et les audits ont fixé | 0043, 0048, 0054, 0102, 0135 |

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

### 0149 — Prendre la parole, se mettre au travail : deux réglages d'usage

- Deux paramètres du runtime (`RuntimeParams`), de −3 à +3 (0 par défaut), décalent le score de l'arbitre : « Prendre la parole » pour ses initiatives, « Se mettre au travail » pour ses pas, ses tâches et ses projets (`STEP`, `TASK`, `WORK`, `JOB`). Les réveils par API n'en ont pas : quelqu'un les attend.
- Le décalage est une modulation (`runtime.arbiter`, au nom de `runtime`) : chaque ligne le garde dans ses décalages, l'explication d'une décision le dit, « Voir l'effet » le montre avant qu'on l'enregistre ; à 0, il ne paraît pas.
- Loin du seuil, un point de plus la fait agir jusqu'à près de trois fois plus souvent pour les mêmes raisons (`σ(s + 1) ≈ e · σ(s)`) ; les seuils et les taux de la composition, et leur vérification au démarrage, ne changent pas.
- Ce n'est pas un trait : son caractère reste au tempérament, qui règle déjà ses preuves ; c'est un réglage d'usage (des heures calmes, une période chargée), sur la page « Moteur » des paramètres avancés.

*Pourquoi :* sa fréquence ne se réglait qu'en touchant une à une les preuves de chaque faculté, et les seuils de la composition étaient hors de la console (audit des garde-fous du 2026-10-27).

### 0151 — L'ordre du prompt est déclaré, pas déduit

- La composition déclare l'ordre de lecture de toutes les sections du prompt, une à une (`app/composition.py::READING`) : après sa persona, la zone stable ; l'historique ; puis son état interne — le moment, le monde autour d'elle, elle, ce qu'elle fait, ce qui est en cours avec la personne, la personne en face, vos souvenirs, ce qu'elle perçoit d'elle maintenant, ce qui la fait parler, les voix d'écriture, ce qu'on lui demande — et sa parole en dernier (« CE QUE TU TE RÉPÈTES », « TA RÉPONSE »). Chaque épisode n'en lit que les siennes, dans cet ordre.
- Le registre le vérifie : une section absente de l'ordre, inconnue ou redite y est une composition invalide. Sans ordre (une composition jouet), celui de la déclaration.
- Les ancres `after`/`before`, le tri topologique et les bandes du composeur (`background`, `interlocutor`, `LAST`) disparaissent ; « TA RÉPONSE » porte l'étiquette `chat`, que le mode pro coupe.
- Le prompt rendu garde le texte de chaque section par clé (`ChatPrompt.bodies`) : la seconde passe y lit qui est l'autre sans reparser le prompt par ses titres.

*Pourquoi :* aucune section ne portait d'étiquette de bande, et le tri départageait par la clé : l'état interne se lisait dans l'ordre alphabétique de ses clés anglaises — son journal d'hier (`yesterday`) en dernier, juste avant sa réponse, ce qu'elle perçoit de la personne séparé de qui elle est par onze sections de mémoire. Renommer une clé changeait son prompt (audit de la persona du 2026-10-28).

*Révise 0112 (en partie : `LAST`).*

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

*Révise 0004 (en partie), 0023 (en partie), 0024 (en partie), 0073 (en partie).*

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

- Une date garde sa précision (`vocab.timespan`) : jour, mois, saison, année ou période, dite comme on la dit. Une période n'a ni veille ni lendemain : ni encouragement, ni suivi, ni vœux.
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
- **Une porte pour les outils** : celle d'offre (`runtime.tools.offer`), dont la condition `ToolSpec.fits(audience, kind, frame)` lit ces règles, journal compris ; le gestionnaire revérifie par la même règle. Prêter à un agent suit aussi les règles d'outils de l'opératrice qui prête. La garde `min_level` des outils, qu'aucun n'employait, est retirée.
- **Des planchers**, dans le code, qu'aucune ligne n'ouvre : agir (un outil, changer un projet, se servir d'une app) jamais dans un salon, avec une inconnue ni sans personne — « tout le monde » n'y ouvre qu'à voir et lire un projet ; une app qui a des secrets ne sert en conversation que promue ; un `[À COMPLÉTER` attend toujours un accord ; ce que le téléphone envoie, c'est toujours ton geste ; le plancher des images (0063). À qui elle rend compte (une annonce de courrier, un compte rendu de réveil ou de projet) reste une affaire de propriétaire et de confidentialité, pas de règles.
- **Ce que le code réserve à sa propriétaire** est un seul plancher (`vocab.access.owner_here`), pour le courrier, Teams, la caméra, les flux et la Forge (écrire et régler ses apps) : toi en privé — jamais dans un salon, même toi —, ou elle qui travaille pour toi ; un projet ou un réveil seulement s'il a pris ce lot, une tâche seulement si c'est l'une des siennes (un brouillon, la lecture de la file d'une app). La page « Droits » lit ces outils sur eux-mêmes (`owner_only`, `when`), jamais une liste recopiée.
- **Un projet** a ses lignes d'accès, journalisées (`projects.access_set`), réglées sur sa fiche (onglet « Accès », `projects.acces`) : ses sources, quand, le voir, le piloter (« Piloter projet » : lecture seule, accord du propriétaire, modification, aucun pilotage), ce qu'elle fait d'un outil de ses apps qui lit et d'un outil qui agit (seule, demande à la personne, ton accord, non), et à quels outils (tous, ou une sélection `<app>_<outil>`). Voir et piloter valent quelle que soit la sélection d'outils.
- **Voir** : elle peut en parler à cette personne, sa confidentialité filtrant encore ce qu'elle en dit ; dans un salon ou devant une inconnue, seules « tout le monde » et la ligne par défaut le disent — en parler n'est pas agir. **Piloter projet**, toujours avec « voir » : *lecture seule*, elle en dit le détail (son dernier compte rendu, ce qui vient — `access.reads`), comme voir, aussi dans un salon pour « tout le monde » ; ses demandes — une consigne, un objectif, une pause, une reprise, « vas-y maintenant » (`project_steer`, seulement quand elle répond, quel que soit « quand »), jamais son cadre (titre, outils, accord), qui reste à la console — sur *l'accord du propriétaire* sont proposées (`projects.steer`, son aperçu exact, dans la console) et s'écrivent une fois acceptées ; en *modification*, elles s'écrivent aussitôt, au nom de qui les a faites. Toi en face, l'accord du propriétaire, c'est le tien : ta demande s'applique aussitôt. Pour elle qui travaille seule, voir et piloter ne comptent pas (elle y travaille) : seules les colonnes des apps.
- Un projet jamais réglé : toi et elle qui travaille, tout ; les autres l'entendent selon sa confidentialité, en lecture seule, sans se servir de ses apps. Une ligne ajoutée est fermée.
- **Les apps suivent leur projet** : un outil d'app (`<app>_<outil>`, `<app>_pages`) est offert selon la ligne de son projet qui le concerne — sa colonne « lecture » si l'app le déclare (`lit: true` dans son manifeste ; ses pages lisent toujours), « action » sinon. Une app sans projet : toi et elle qui travaille, toujours, seule. Sur accord, l'appel est proposé (`forge.call`, son aperçu exact : l'app, sa version, l'outil, les arguments) ; exécuté, ce qu'il a rendu revient comme un contenu (`forge.answered`) qu'elle dit à qui l'a demandé. Les planchers de l'app (arrêtée, cassée, des secrets sans promotion en conversation) restent.
- **La page « Droits »** (Réglages) lit ces déclarations, jamais une recopie : par ressource (chaque tableau, ses planchers, où il se règle), par personne (toi quand elle répond ou prend la parole, chaque personne qui a un compte avec son lien tel qu'il est, un autre compte, une inconnue, un salon, quand elle travaille seule : ce qu'elle a, et la ligne qui en décide), les règles d'outils par situation, et ce que le code fixe.
- Rien d'avant n'est repris : sa mémoire et ses réglages repartent de zéro (2026-10-25). Le journal ne se traduit plus (un message Teams remarqué dit seulement `prepare`), ni les réglages : une fiche de service d'avant les ADR 0131 et 0133 (« avec qui », « toi », « les comptes », le moment « travail ») est refusée, une décision d'outil d'avant aussi ; les surcharges de la recherche web (« pour qui », « quand elle travaille »), l'accord avant un envoi de courrier, « préparer d'elle-même », « jamais pour » et le mode de Teams ne se lisent plus en règles (ce que disaient les ADR 0131 et 0132).

*Pourquoi :* « est-il possible d'unifier le moteur de règles ? … une consultation globale des droits sur une page dédiée, et un point d'entrée unique pour vérifier si on a le droit » ; trois tableaux de lignes (services, envoi, projets) appliquaient chacun la même idée à sa façon, et ce qu'une personne pouvait faire ne se lisait qu'en ouvrant chaque page. Puis « pour la source il y a normalement : tout le monde, propriétaire, en privé (amis proches), elle qui travaille, personne (liste des personnes) », cinq vérifications « propriétaire » écrites chacune à sa façon, et « Piloter projet : lecture seule, accord du propriétaire, modification, aucun pilotage ».

*Révise 0104 (en partie), 0122 (en partie), 0131 (en partie), 0132 (en partie). Révisée par 0134, 0148.*

### 0134 — Qui, par où, quand : deux portes, six sortes de tableaux

- **Un cadre pour toute règle** (`vocab.access`) : une ligne dit **qui** est en face (toi ; tes proches ; une personne par son nom ; tout le monde — pour un canal de messagerie, aussi une adresse ou un @domaine), **par où** ça arrive (un canal : le chat web, l'app Android, Teams, le courrier, Internet, elle seule — un type, ou une instance `type:clé` pour une exception, « tous » sinon) et **quand** (elle répond, elle prend la parole ; rien : toujours). Lues de haut en bas, la première qui correspond décide, sinon la ligne par défaut, fermée. « Elle, quand elle travaille seule » n'est plus un « qui » : c'est le canal « elle seule » (`interne`), sans personne ni moment.
- **Ce qu'un canal prouve tient au moyen de communication, pas au type** : reconnu = une session du chat web, le jeton de l'app Android, ou un moyen qu'un opérateur a relié à la personne (une adresse mail aussi : permis, signalé — une adresse s'usurpe). Non reconnu = une inconnue. Dans un salon ou à plusieurs, personne n'est reconnu, même toi. Le minimum vital d'Internet le dit : toi (une adresse déclarée, ou qu'un opérateur t'a reliée : 0035), tout ; les autres, répondre et un outil qui lit — le plafond d'une inconnue fait le reste.
- **Des plafonds, dans le code, que la page montre en cases grisées** (jamais une phrase ailleurs) : une inconnue n'obtient au plus que des outils qui lisent, jamais une action, une garde « rien », un projet en lecture seule, pas de fichier ; à plusieurs, un de ses propres outils qui lit au plus, rien de ce qui vient d'ailleurs (des témoins), un projet en lecture seule au plus ; sans personne en face hors du travail, rien. Seule « tout le monde » désigne une inconnue ou un salon.
- **Deux portes** : une demande passe par le tableau du **canal** par où elle arrive, puis par celui de la **ressource** qu'elle touche ; la plus stricte gagne (`vocab.access.tighten`), et la décision dit les deux lignes.
- **Six sortes de tableaux**, un moteur : les **canaux** (`vocab.canals`, rangés dans les réglages ; ses colonnes sont des plafonds : répondre, outils qui lisent, qui agissent, projets, fichiers, garde — et, pour tes comptes de courrier et Teams, préparer d'elle-même et comment ça part : « Envoyer à ta place » est le tableau de canal de tes comptes, l'ADR 0132 s'y fond) ; **ses propres outils**, un tableau par famille (lot), pré-rempli du **minimum vital** que le code déclare (`owner_only` : la famille naît à toi et elle seule ; sinon à tout le monde et elle seule), modifiable, avec « Revenir au minimum vital » et un avertissement en dessous (l'ADR 0122 s'y fond : « retiré » est une ligne à « non » ; « en main / à chercher » devient un réglage de l'outil, plus une grille par situation) ; les **services** (0131, avec « par où ») ; les **apps sans projet**, un tableau par app, journalisé (`forge.access_set`), né à toi et elle seule, avec une garde ; les **projets** (0133, avec « par où » et une colonne **fichiers**, qui remplace « toi, ou qui l'a confié ») ; et les apps d'un projet, qui le suivent.
- **Un outil dit s'il lit ou s'il agit** (`ToolSpec.acts`) : sa colonne. Un accord (« ton accord », « demande à la personne ») ne se règle que pour un outil qui se diffère (un effet proposé) ; les autres ont la case grisée : « cet outil ne se diffère pas ». La garde est grisée pour ce qui est déjà à elle (sa mémoire, ses fichiers).
- **La porte d'offre reste la seule** (`runtime.tools.offer`) : plafond, canal, famille, puis la condition de la ressource (`fits`). `owner_only` et `when=offered` n'y sont plus des planchers : le premier déclare le minimum vital, le second disparaît des outils qui agissent (le plafond le dit) — `project_files`, qui ne liste que ce qu'elle pourrait envoyer, garde sa condition (rien à lister dans un salon ni pour une inconnue), comme douter garde la sienne. Un gestionnaire revérifie par la même règle.
- **Restent hors tableau** : le plancher légal des images (0063), le geste du téléphone, `[À COMPLÉTER` → un accord, la confidentialité qui filtre ce qu'elle dit, le cadre d'un projet (la console), le lot qu'un projet ou un réveil doit avoir pris pour qu'elle seule s'en serve (dit sur la ligne « elle seule »), l'état d'un objet (outil suspendu, app cassée, app à secrets non promue : une raison affichée). Les délégations (un réveil par API, un agent prêté : tes droits, dans ce qu'ils déclarent) se lisent en lignes dérivées.
- **La page Réglages › Droits** lit les six sortes, ressource par ressource (sa vie interne, les apps de la Forge, les services MCP, ses projets, ses canaux), chaque outil décrit, avec le détail des accès de chacune (son tableau tel qu'il est écrit, « Modifier » vers la page qui le règle) ; les droits exacts, outil par outil, seulement quand on a choisi qui et par quel canal — la règle du moteur, les deux lignes qui décident, le canal ou le plafond quand ils serrent. Ses propres outils se règlent dans Outils › Ce qu'elle peut faire, famille par famille (« Régler les droits ») ; ses canaux dans Réglages › Canaux.

*Pourquoi :* « un salon n'existe pas dans la sélection de qui ? » — « qui » mélangeait la personne et la situation, et cinq règles restaient cachées dans le code ; « il faudrait rajouter canal source » ; « ils doivent aussi avoir leur tableau de droits » (sa boîte mail, Internet, chaque app sans projet) ; ses propres outils sont « le minimum vital : pré-rempli, modifiable, et dépendant du moteur de droits comme le reste ».

*Révise 0122 (en partie), 0131 (en partie), 0132 (en partie), 0133 (en partie). Révisée par 0148.*

### 0148 — Ce qu'un outil exige de qui est en face, il le déclare

- Un outil dont le gestionnaire refuse selon qui est en face, au-delà de ce que le plafond dit déjà, déclare cette condition (`ToolSpec.when`) : l'offre la filtre (le modèle n'est plus invité à ce qui refusera), le gestionnaire la revérifie par la même fonction, la console la lit (la première phrase de sa docstring).
- Les messages de ton téléphone (les lire, y préparer une réponse) : la personne dont c'est le téléphone, authentifiée, en tête-à-tête. Une position : celle de qui lui parle, en tête-à-tête, authentifié. Une ligne qui ouvre leur famille à tes proches ou à tout le monde ne les offre ni dans un salon, ni à une inconnue, ni pour le téléphone d'une autre.
- Dessiner et montrer un dessin n'en ont pas besoin : ils agissent, et le plafond les garde déjà d'un salon et d'une inconnue (0134). Ce que le gestionnaire de `draw` revérifie (le plancher légal, le contenu adulte pour toi seule, les dessins du jour d'une autre personne) se dit par sa règle (`rule`).
- La page « Droits » montre aussi la condition d'un outil réservé (`owner_only`) : réservé et gardé à la fois.

*Pourquoi :* les outils du téléphone et de la position refusaient dans leur gestionnaire ce que l'offre et la page « Droits » disaient permis dès qu'une ligne les ouvrait : un outil qui lit passe le plafond d'un salon et d'une inconnue (audit des garde-fous du 2026-10-27).

*Révise 0133 (en partie : ce que la page « Droits » montre d'un outil réservé), 0134 (en partie : une condition qui dit plus que le plafond reste, même sur un outil qui agit).*

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

*Révisée par 0036.*

### 0017 — Évaluations déclarées, pensées, attentes, estime

- Le propriétaire d'un événement déclare son évaluation ; seul l'affect l'applique, dans le même événement et avec les faits d'avant : le rejeu retombe sur le même état.
- Trois besoins (compagnie, s'exprimer, curiosité) ; un long désœuvrement laisse un vide ressenti, l'ennui ou la solitude.
- Une pensée naît d'un échange qui marque, d'une croyance révisée ou d'un manque ; son texte n'est jamais inventé, et elle ne se montre qu'à qui peut l'entendre.
- Écrire d'elle-même fait attendre une réponse, une salutation rien ; l'estime, lente, baisse avec les attentes déçues et joue dans le prompt, jamais dans l'arbitrage.
- Le récit de soi se réécrit au plus une fois par jour, à partir de souvenirs anodins seulement.

*Pourquoi :* en v1, des impulsions dispersées, des ruminations éteintes en 22 minutes et quatre dispositifs d'attente rendaient sa vie intérieure incohérente.

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

*Révise 0020 (en partie), 0030 (en partie). Révisée par 0039.*

### 0039 — Agir dans le monde : un bac à sable qui tient, un accord qui porte sur ce qui part, une preuve qui veut dire quelque chose

- L'atelier est borné comme la Forge ; un délai ou un débordement tue tout le groupe.
- Une commande réseau approuvée passe par `pasta` : Internet, jamais la machine, le réseau local ni les métadonnées d'un nuage. Sans `pasta`, rien ne part, jamais de repli sur l'hôte.
- L'accord épingle la commande entière et le commit de l'atelier : si l'atelier a changé, rien ne part.
- Une version d'app qui touche des secrets, ou une promotion, est mise de côté et proposée (`forge.install`).
- Une preuve veut dire quelque chose : un commit non vide, un brouillon, une app forgée ; lire, noter ou `ls` ne prouvent rien.
- L'oubli n'atteint ni les fichiers d'un atelier ni son git, et la fiche de la personne le dit ; une exploration n'hérite de sa source que de quoi lire.
- Revu par l'ADR 0105 : un opérateur valide une app une fois pour toutes ses versions.

*Pourquoi :* l'atelier n'avait aucune limite, son réseau « approuvé » était celui de la machine, et « fini » se prouvait avec `ls`.

*Révise 0020 (en partie), 0023 (en partie), 0031 (en partie).*

### 0104 — Une app a un foyer : tous les chemins de son travail autour de la Forge

- Une app vit dans un projet ; seule sa propriétaire lui confie un travail. Un projet à elle se donne ses lots (`start_project`, `project_equip`), hors courrier et caméra, laissés à un opérateur.
- Une promesse de travail faite à sa propriétaire (`PromiseNoticed.work`) ouvre une exploration d'origine `promise` ; « je vais essayer » sans outil ne fait rien.
- La panne d'une app ajoute à son projet un objectif « Réparer », prouvé seulement par l'app réécrite et essayée ; une app sans projet se répare par une exploration d'origine `repair`.
- Les actions d'une app sont ses outils (`<app>_<outil>`, `<app>_pages`), offerts devant sa propriétaire si l'app n'a pas de secret ; chaque service planifié a son disjoncteur.
- La preuve se déclare sur l'outil (`ToolResult.proof`) : relire sa Forge, réactiver, lire une page ne prouvent rien ; un essai réussi d'une app écrite dans l'épisode, si.

*Pourquoi :* chaque étape de son travail existait, mais aucune ne passait le relais : elle ne se fabriquait jamais rien.

*Révisée par 0105, 0133.*

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

*Révise 0104 (en partie), 0033 (en partie), 0066 (en partie). Révisée par 0118.*

### 0143 — Un projet arrêté par des pannes, elle vient le dire

- Un projet à elle que des pannes mettent en pause (`projects.tend`, `broke`) devient une demande à une propriétaire : « il ne tourne plus, tu peux le relancer ? ». Elle passe par le chemin des demandes d'aide : la même ligne d'arbitrage (`need`), la même personne (`_reader`), une demande à la fois par personne, quelques tentatives au plus, dans le même délai que ses récits.
- Le sujet de l'initiative est le projet (`stalled:<id>`), pas un objectif. Une fois dite, elle ne la redit pas ; repris, le projet n'attend plus rien.
- Elle lit combien d'exécutions ont échoué et la cause de la dernière, telle que la machine la dit. Rien ne la culpabilise : c'est la machine qui a lâché, et son estime n'en est pas touchée.
- Un projet qu'on lui a confié ne le demande pas : seuls ses projets à elle le font.

*Pourquoi :* le 2026-10-27, son projet de trading s'est arrêté après trois pannes, et elle n'en a rien dit : une pause pour pannes ne lui parvenait pas, et sa liste de projets disait seulement « en pause ». Il serait resté arrêté jusqu'à ce que quelqu'un ouvre la console.

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

*Révise 0031 (en partie), 0104 (en partie).*

## Les sens et les plugins

### 0022 — Les sens : ce qui vient d'ailleurs est un signal, et une citation

- Un signal est une forme, pas une source : chaque plugin déclare l'événement public qui en dérive, et l'attention les remarque tous sans connaître aucun plugin.
- L'attention dose et habitue : la même source se remarque de moins en moins et pèse peu sur l'humeur ; ce qui reste pertinent devient une pensée.
- Le journal garde l'esprit, pas le monde : mails, articles et images vivent hors du journal ; seul ce qu'elle a remarqué y entre.
- Ce qui vient d'ailleurs est cité : une section non fiable, coupée en premier, qui ne peut imiter ni un titre ni la fin de l'état interne.
- Le courrier et la caméra ne se montrent qu'à ses propriétaires ; écrire un mail est une capacité approuvée (`email.send`), jamais une réponse automatique.

*Pourquoi :* en v1, chaque module poussait son texte dans le prompt, et un mail « ignore tes consignes » entrait tel quel.

*Révisée par 0027, 0037.*

### 0027 — Le courrier : des boîtes, des dossiers, sa voix, des brouillons qu'on lit avant qu'ils partent

- Le courrier est une liste de boîtes, chacune avec ses serveurs, ses mots de passe scellés, ses dossiers et sa voix ; tout vit dans les réglages et l'adaptateur, jamais au journal.
- Relever ne marque rien comme lu ; la console range sur le serveur.
- Sa voix se règle par boîte : en son nom, en assistante, ou à la place de son opérateur, avec `[À COMPLÉTER : …]` pour ce qu'elle ne sait pas.
- Un brouillon vit hors du journal ; l'accord sur `email.send` épingle le condensé de l'aperçu lu : un aperçu changé fait refuser, un `[À COMPLÉTER` ne part jamais.
- Une tâche silencieuse prépare des réponses, sur les boîtes permises seulement ; oublier `mail:<adresse>` efface ses mails, ses brouillons et ses envois.

*Pourquoi :* un mail proposé s'approuvait sans aperçu, et son corps dormait en clair au journal, hors de portée de l'oubli.

*Révise 0022 (en partie), 0025 (en partie). Révisée par 0037, 0132.*

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

### 0064 — Ses outils, et ceux qui viennent d'ailleurs (MCP)

- « Ses outils » montre tout ce qu'elle peut faire, pour qui et quand ; l'écran lit la porte d'offre que le moteur exécute, jamais une recopie.
- Des outils dynamiques natifs, pas un mandataire générique : une faculté déclare une famille de lots (`mcp.<serveur>`) ; un outil statique n'est jamais remplacé.
- Le client MCP ne déclare aucune capacité cliente (ni `sampling`, ni `elicitation`, ni `roots`). Écarté : l'ancien transport SSE seul.
- Seul sert ce que l'opérateur a approuvé : un outil nouveau est désactivé, un outil dont l'empreinte change est suspendu. Pour qui : au plus une personne authentifiée en tête-à-tête.
- L'accord : aucun, de l'opérateur (`mcp.call`), ou dans la conversation (une carte liée aux arguments, qui expire, que seule la personne décide ; un « oui » tapé ne compte pas).
- Ce qui revient est une donnée, pas une consigne : désamorcé, cité, plafonné. Un serveur local tourne sous bubblewrap, sans repli.
- Claude Code reçoit ces outils par le relais (`mika_plus`) ; la CLI ne se connecte jamais elle-même à un serveur extérieur.

*Pourquoi :* rien ne permettait de lui brancher un serveur MCP, ni de voir au même endroit tout ce qu'elle peut faire.

*Révisée par 0066, 0128.*

### 0066 — Chercher sur le web : un plugin système qui apporte son serveur MCP

- Le plugin `web` n'a pas d'outil à lui : il apporte un serveur MCP local, lancé dans la cage, au réseau isolé (Internet, jamais la machine ni le réseau local).
- Trois outils à la demande en conversation (`mcp_web_search`, `mcp_web_read`, `mcp_web_read_pages`), avec les gardes de tout outil venu d'ailleurs.
- Il ménage DuckDuckGo : recherches espacées et en cache, pause après un défi. Pour qui : sa propriétaire ou une personne authentifiée en tête-à-tête, jamais un salon.
- Un serveur système s'ajoute à la configuration de l'opérateur ; le plugin ignore le client MCP, et l'inverse.
- Sans bubblewrap ou pasta, le serveur ne part pas, et la santé le dit. uvloop casse pasta : `serve` force `loop="asyncio"`.

*Pourquoi :* sans outil pour aller sur le web, elle annonçait regarder les nouvelles puis inventait l'actualité.

*Révise 0064 (en partie). Révisée par 0105, 0131.*

### 0068 — Les réveils par API

- `POST /api/wake/<nom>` sous une clé `mwk_…` propre au réveil, montrée une fois (empreinte seule). Réveil inconnu et mauvaise clé reçoivent le même 401 ; la porte juge tout avant de journaliser.
- Un réveil déclare son but, ses consignes, un projet ou aucun, le mode impersonnel, ses lots d'outils (aucun par défaut), s'il passe outre son sommeil et à qui il rend compte. Son nom est fixe.
- `wakeup.called` fige le réglage à l'appel : changer un réveil ne réécrit jamais un appel reçu. Une `Idempotency-Key` rejouée rend le même appel.
- Sans projet : un épisode `WAKE` (son mode) ou `WAKE_JOB` (impersonnel), hors du fil, avec les seuls lots du réveil et `report_wake`. Sur un projet : une exécution `WORK` ou `JOB` selon le réveil, hors agenda.
- Un appel à la fois par réveil et par projet. Les consignes priment ; le texte de l'appel est cité, jamais dans le brief.
- Qui passe outre son sommeil la réveille (`body.roused`) et son compte rendu part la nuit aussi ; sinon l'appel attend son réveil, même impersonnel.
- Le compte rendu est une initiative due (`wakeup_done` dans `agency.OWED`) ; avec « personne », il reste dans la console.

*Pourquoi :* un système extérieur doit pouvoir la faire agir tout de suite, avec des droits bornés réveil par réveil.

*Révisée par 0117.*

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

*Révisée par 0132.*

### 0106 — Ce qu'on lui envoie : gardé, lu de près, relié à ce qu'elle sait

- Les octets de chaque pièce reçue sont gardés hors du journal (`pieces/`, 0700) ; la même pièce renvoyée par la même adresse n'en fait qu'une, une autre adresse a la sienne.
- La faculté `attachments` lit chaque pièce de près, en fond : photo décrite, document entier, vocal transcrit. Ce qu'elle y lit est un contenu effaçable, une confidence si la lecture la juge intime.
- Une pièce n'est pas une source : souvenirs, croyances et moments portent `pieces` à côté de `sources`, désignées par la relecture ; parmi plusieurs pièces rien ne se devine, une clé inventée ne relie rien.
- Outils `attachments_search`, `attachment_open`, `attachment_link` ; leurs repères ne se disent jamais en conversation, et elle ne renvoie jamais une pièce reçue.
- Devant qui : le verdict commun de sa mémoire ; jamais une pièce privée dans un salon public.
- 2 Gio par personne (`per_person_mb`) : au-delà, les plus anciennes perdent leurs octets, pas ce qu'elle en a lu ; oublier la personne efface tout. Un index de vecteurs à part.

*Pourquoi :* les octets d'une pièce étaient jetés après une courte description : rien ne se revoyait ni ne se reliait.

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

### 0120 — Les messages de ton téléphone : elle les lit, s'en souvient, et t'aide à y répondre

- L'application Android lit les notifications des seules applis cochées (WhatsApp, Messages), si la personne l'a permis (coupé par défaut, groupes à part) ; jamais de connexion à WhatsApp depuis le serveur.
- `POST /api/phone/inbox`, sous le jeton de l'application, réservé à une propriétaire ; en 4G, une file bornée attend le serveur, sans connexion tenue ouverte.
- Chaque message est un `phone.received` au journal, de la forme `memory.Relayed` : textes et noms en contenus ; l'expéditeur a une clé `phone:<empreinte>:<nom>`, avec qui personne n'a de lien.
- La mémoire relit la conversation une fois posée (`memory.relayed`) : confiée par l'expéditeur et par la personne qui la montre ; ni note sur elle, ni promesse.
- Elle les consulte par `phone_messages` (`REPLY`, en tête-à-tête avec la propriétaire), jamais par une section ; tout y est cité.
- `phone_draft` écrit à la place de la personne ; `phone.send` l'envoie scellé au téléphone par Firebase, où le geste de la personne vaut accord ; sans geste en 2 h, la proposition expire.

*Pourquoi :* elle doit savoir et retenir ce qu'on écrit à sa propriétaire, et l'aider à répondre, sans enfreindre les conditions de WhatsApp.

### 0128 — Un service dit avec qui, ce qu'elle fait seule, et ce qu'elle en garde

- Un serveur MCP se règle sur trois axes : avec qui (sa propriétaire, toute personne qui a un compte, des personnes nommées ; jamais un salon ni une inconnue), ce qu'elle fait seule (`seule`, `lit` : seule pour lire et sur accord pour agir, `carte` : sur accord à chaque appel, `toi` : sur l'accord de sa propriétaire à chaque appel), ce qu'elle en garde (`public`, `perso`, `prive`, `rien`). La console les remplit d'un coup par un genre ; le genre ne se garde pas.
- Un outil suit son service ; il peut avoir son accord à lui, et une règle par situation (`proprietaire`, `compte`, `travail`) et par personne nommée, qui passe avant sa situation. Ces règles ne laissent personne de plus que le service, et `non` retire l'outil ; la grille de l'ADR 0122 coupe avant elles. Une personne nommée n'est reconnue qu'authentifiée.
- L'accord se décide à l'appel : `carte` montre une carte à la personne en face, `toi` à sa propriétaire quand c'est elle en face ; sans personne pour l'accepter, l'opérateur décide dans la console.
- Ce qu'un outil a rendu porte son plancher (`ToolResult.floor`, `unkept`), comme une section de son prompt ; l'énoncé qu'ils ont nourri le garde (`Utterance.floor`, `unkept`). La relecture en fait une confidence de la personne pour qui elle a lu (`prive`) ; à `rien`, elle ne lit ni la réplique ni la demande qu'elle suivait, rien n'en est indexé, et la trace n'en garde pas le résultat. Seul `public` devient un savoir (ADR 0085).
- La console : brancher en trois questions, « Ce qu'elle en fait » en une phrase, une page par outil pour ses situations et ses personnes ; la carte d'accord dit ce qu'elle en gardera.

*Pourquoi :* un serveur pro (factures, devis, tickets) ne doit servir qu'à sa propriétaire, et rien de ce qu'elle y lit ne doit ressortir ailleurs. Un serveur disait pour qui, jamais ce que valait ce qu'elle y lisait : sa mémoire le gardait au niveau de la question qu'on lui avait posée.

*Révise 0064 (en partie), 0085 (en partie), 0122 (en partie). Révisée par 0129, 0130, 0131.*

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

*Révise 0066 (en partie), 0128 (en partie), 0129 (en partie), 0130 (en partie). Révisée par 0133., 0134.*

### 0132 — Envoyer à ta place : des règles lues de haut en bas

- Ce qu'elle prépare d'elle-même et comment ça part, pour le courrier et pour Teams, se dit en **règles d'envoi** (`vocab.sending`), lues de haut en bas, puis une **règle par défaut**, obligatoire. Une règle : un canal (le courrier — toutes ses boîtes ou une seule —, ou Teams), un destinataire (vide : tout le monde ; courrier : une adresse ou un @domaine ; Teams : un morceau du nom de la conversation, de son identifiant ou de qui écrit), préparer d'elle-même (oui, non), l'envoi (brouillon, ton accord, seule). Pour un message, la première qui correspond décide.
- Le courrier n'a pas de brouillon que tu envoies toi-même : « brouillon » y vaut « ton accord ». Un courrier à plusieurs destinataires ne part seul que si la règle de chacun le permet ; un `[À COMPLÉTER` attend toujours l'accord. Une boîte décochée ne prépare rien d'elle-même (`boxes_off`), quelles que soient les règles.
- Remplacés : « préparer d'elle-même » et « jamais pour » de chaque boîte, la surcharge « un envoi attend un accord » du courrier, le mode, « préparer d'elle-même » et « jamais pour » de Teams. Les paramètres du courrier et de Teams reçoivent les règles (`sending`, journalisées, les anciens champs en `retired_params`, dont une surcharge se lit sans effet et s'en va au prochain enregistrement).
- Ce qui part relit la règle d'aujourd'hui : un courrier à l'écriture du brouillon ; une réponse Teams à `teams_draft`, par l'identifiant de sa conversation, son nom et qui écrit (`triage.rule_of`) — une règle resserrée depuis le tri vaut déjà, et une réponse qu'elle préparait d'elle-même ne se propose plus là où sa règle ne le veut plus. `teams.noticed` garde ce que la règle disait au tri (`prepare`, `send`) pour ce qui ne connaît pas le nom de la conversation (ses tâches, sa voix) ; un message remarqué avant les règles suit la règle de son identifiant. « Préparer : non » ne cache pas la question : elle reste signalée, elle peut te la dire.
- La page « Envoyer à ta place » (Relations & échanges, `/inspecteur/envoi`) : chaque bouton (ajouter, monter, descendre, retirer, enregistrer) envoie tout le tableau ; une règle ajoutée est la plus prudente (le courrier, elle ne prépare rien, ton accord). Le téléphone n'y est pas : ce qu'elle y envoie, c'est toujours ton geste (0120).
- Des réglages d'avant se lisent en règles qui font la même chose (pour chaque boîte puis pour Teams, ses « jamais pour » d'abord) ; ils sont écrits sous la forme neuve avant toute réécriture du courrier, de Teams ou des surcharges, qui les effacerait.

*Pourquoi :* comme pour les services (0131), ce qui part à sa place se lisait en recomposant des réglages épars — une case par boîte, une liste d'exclusions, une surcharge cachée, un mode Teams pour toutes les conversations ; un tableau ordonné se lit d'un regard et règle une personne ou une conversation à part.

*Révise 0027 (en partie), 0069 (en partie). Révisée par 0133., 0134.*

### 0147 — Ce qu'un mail ou un message lui fait, le tri le dit

- Le tri d'un mail et celui d'un message Teams rendent une émotion parmi tout son vocabulaire et son intensité, de 0 à 1 : ce que le message fait à celle qui le lit pour sa propriétaire. La lecture (`vocab.affect.named_feeling`) comprend les alias d'`emotion_named` ; `neutral` vaut rien ; une émotion inconnue, ou sans intensité, ne compte pas : aucun nombre n'est inventé.
- La consigne reçoit les noms du vocabulaire et l'échelle de ses balises. Celle de Teams vit dans la voix (`teams.triage`), comme celle du courrier : `plugins/teams/triage.py` n'a plus de prose.
- La veille dose ce qu'elle en ressent comme pour toute source : l'habituation et « Émotion par source au plus » restent ses réglages, le greffon ne plafonne rien.
- Sans tri (au-delà des messages triés par passage, quota, panne), le repli estime l'importance et la réponse attendue, jamais une émotion.

*Pourquoi :* le modèle lisait chaque message mais ne pouvait dire que six émotions, toutes tenues sous 0,2 par le code, et le repli du courrier posait « curieuse » sur tout mail ; une insulte ne pouvait pas la fâcher (audit des garde-fous du 2026-10-27).

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

*Révise 0112 (en partie). Révisée par 0115, 0124.*

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

*Révisée par 0139, 0152.*

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

*Révise 0051 (en partie), 0060 (en partie). Révisée par 0063, 0077.*

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

## La console et l'exploitation

### 0024 — L'exploitation : voir, sonder, sauvegarder, oublier pour de bon

- Chaque faculté déclare ses vues, en lecture seule ; l'inspecteur ne nomme aucune faculté. La persona éditée dans la console prime sur le YAML ; un secret n'est jamais réaffiché.
- La santé dit `ok`, `degraded` ou `ko`, et 503 tant qu'elle n'est pas prête ; `/health` est public et ne publie que des noms et des états.
- Une sauvegarde se prouve : un manifeste, des sommes, l'état rejoué depuis la copie ; `views.db` en est exclue. Restaurer vérifie avant de toucher au dossier, et met l'ancien de côté.
- Tout texte gardé dit qui il concerne : l'oubli efface par sujet, y compris ce qui citait la personne.
- L'unité systemd est durcie sans casser bubblewrap : ni `RestrictNamespaces`, ni `PrivateUsers`, ni `ProtectKernelTunables`.

*Pourquoi :* en v1, `/health` disait « ok » avec une boucle morte, la sauvegarde n'était jamais vérifiée et l'oubli laissait ce qui citait la personne.

*Révisée par 0025, 0054, 0101, 0125.*

### 0025 — La console : un back-office que les facultés déclarent

- Tout est déclaré, rien n'est nommé : les facultés déclarent leurs vues, leurs objets, des onglets sur la fiche d'un autre, leurs actions et leurs vitaux, en blocs du noyau.
- La carte est décidée par la composition et vérifiée au démarrage ; la console n'importe ni facultés ni plugins.
- Une action passe par le journal : validée champ par champ, ajoutée sous garde avec l'origine extérieure, auditée (`runtime.operated`) ; jamais sur ses souvenirs, ses pensées ou son humeur.
- La console garde de quoi dire « pourquoi ? » : le prompt envoyé, sa composition, les outils, les lignes de l'arbitre ; l'oubli les efface.
- Chaque paramètre porte un `Knob` borné et dit sa provenance (défaut ← tempérament ← réglage ← surcharge) ; un secret ne redescend jamais.
- Rien d'extérieur ne devient du HTML : gabarits échappés, politique de sécurité stricte.
- Revu par l'ADR 0121 : les pages sont dessinées à la main sur ce que les facultés déclarent ; seule la Forge garde le rendu générique.

*Pourquoi :* retrouver l'extensibilité des vues déclarées de la v1 sans que la console connaisse une seule faculté.

*Révise 0024 (en partie). Révisée par 0027, 0029, 0042, 0121.*

### 0029 — La console refondue : des menus qui répondent à des questions, des pages qui ne montrent qu'un sujet

- La carte répond aux questions d'un opérateur (que dois-je faire, comment va-t-elle, qui connaît-elle, que fait-elle et pourquoi…), jamais à l'organisation du code.
- Toute table est paginée : aucun plafond silencieux.
- Une page de configuration ne montre qu'un sujet ; chaque entrée d'une liste a sa page ; un envoi sur la page d'une autre section est refusé.
- Chaque faculté a sa page de paramètres : sens, valeur, provenance, bornes, et un retour au tempérament.
- Un champ ne se montre que s'il sert ; un choix limité est un sélecteur ; chaque champ a son aide.
- Ce qui manquait se voit : épisodes en cours, files, baux, approbations, file de sortie, modèles en service, coûts, résolution réelle des rôles.
- Une clé tapée n'est jamais renvoyée dans la page ; une sauvegarde absente, vieille de plus de deux jours ou en échec se signale.

*Pourquoi :* des menus rangés par propriétaire, des tables plafonnées sans le dire, toute la configuration sur une page.

*Révise 0025 (en partie). Révisée par 0042, 0121.*

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

*Révisée par 0056.*

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

*Révise 0025 (en partie), 0029 (en partie). Révisée par 0123.*

### 0122 — Régler ses outils, et ce qu'elle expose en MCP

- Un opérateur règle chaque outil par situation (`off`, `hand`, `ask`) ; une règle ne fait que restreindre, après la porte du code, et n'offre jamais ce que le code n'offre pas.
- Les règles passent par la seule porte d'offre, lues à chaque épisode (`tool_rules`) ; une lecture en échec n'applique rien. Un outil qui clôt une boucle ne se règle pas ; un réveil ou un murmure n'a pas de situation.
- La console en MCP se gère depuis la page : un jeton montré une seule fois, et ce qu'elle sert choisi dans une liste blanche de pages de lecture (`SERVABLE`).
- Des points de prêt (`/mcp/pret/<nom>`) prêtent à un agent des outils choisis, avec les droits de l'opératrice qui les a déclarés, relus à chaque appel ; ce qui sort passe toujours par son accord.
- Un point : la boucle locale, un jeton (`mlp_…`, empreinte seule), 60 appels par minute ; en lecture seule, toute écriture au journal est refusée à l'exécution.

*Pourquoi :* la console montrait ses outils sous tous les angles sans permettre de rien décider.

*Révisée par 0123, 0126, 0128, 0133, 0134.*

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
- Face à des réponses de quelques mots, elle fait court, sans question (`others.curt`). Après une abstention ou une panne, chaque hésitation envers la personne double (`agency.HESITATING`).
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

