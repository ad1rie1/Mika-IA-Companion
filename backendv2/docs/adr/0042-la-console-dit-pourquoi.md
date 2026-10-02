# 0042 — La console dit pourquoi, en mots, et ne laisse rien partir par erreur

**Contexte.** L'audit de la console (constats CON-1 à CON-30, et KER-28) a trouvé une console sûre contre
l'injection (aucun XSS en 5 024 requêtes hostiles) mais fragile ailleurs. Un fuseau inventé, importé en YAML,
mettait **toute** la console en panne — conversation comprise — alors que `/health` répondait 200. La page de
connexion se laissait deviner sans limite. La touche Entrée, dans le champ « note » d'une approbation, approuvait ;
dans les paramètres d'une faculté, elle « revenait au tempérament ». Renommer un fournisseur effaçait en silence
les rôles qui le visaient. La garde d'une action d'opérateur comparait la tête du journal à elle-même : elle ne
voyait jamais rien changer (KER-28). Un formulaire dont l'action avait **échoué** répondait « déjà envoyé » au
renvoi. Les vues mentaient par endroits : le choix de l'arbitre d'un épisode se retrouvait par approximation (le
plus récent avant le départ, souvent celui d'un autre), le journal des modifications perdait des lignes entre
deux pages, la chronologie présentait une action d'opérateur comme un épisode « en cours ou interrompu », des
badges ne s'éteignaient jamais, « total non connu » s'affichait pour trois lignes, « Plus anciens » menait à une
page vide. Et tout se lisait en jargon : `user_1`, `memory.consolidate`, `woken_at_night`, `log-odds`,
`stance`, `JOB`, `0.000 $`, `UnconfiguredRole(…)`. Enfin, la question que l'opérateur se pose le plus — **« pourquoi
a-t-elle dit ça ? »** — demandait d'ouvrir cinq onglets d'épisode et de lire des clés.

**Décision.**

1. *Une page « Pourquoi a-t-elle dit ça ? » par parole* (`/inspecteur/parole/<seq>`, `inspector/pages/why.py`).
   Elle rassemble, en mots : ce qu'elle a dit (à qui, quand, avec quelle voix) ; **ce qui l'a fait parler** — le
   message auquel elle répondait, ou **la ligne exacte de l'arbitre** et son calcul pas à pas (chaque preuve nommée,
   chaque modulation, l'attente, le seuil, le score, le taux, le tirage, les autres lignes du moment) ; **ce qu'elle
   avait sous les yeux** — les sections du prompt nommées en français, gardées, rognées ou coupées et pourquoi ;
   **ce dont elle s'est souvenue** — souvenirs, croyances, promesses, échanges, buts, projets, avec leur texte ; **ce
   qu'elle a fait** — les outils, leurs arguments et leurs résultats. Les identifiants restent dans « Détails
   techniques ». Elle est liée depuis le fil, l'onglet « Échanges » d'une personne, chaque épisode et chaque
   événement de parole ; `Ref.why(seq)` (noyau) la rend accessible à toute vue.
2. *Le choix exact de l'arbitre.* Un épisode lancé par l'arbitre lit le numéro de son `kernel.selected` quand il le
   porte (`EpisodeStarted.selected`, lot WP9a) ; sinon le **premier** choix après la tête notée par son déclencheur
   (`selected:<tête>`) qui a tiré cette sorte envers cette cible — jamais « le plus récent avant le départ ».
   Un prélude (le murmure juste avant une initiative, déclencheur `prélude:selected:<tête>`) n'a ni la sorte ni
   la cible du choix qu'il précède : il suit la ligne tirée, quelle que soit sa cible.
3. *Tout se nomme au même endroit* (`inspector/names.py`). Une adresse devient le nom de qui parle derrière ; une
   sorte d'épisode, une issue, un rôle, une voie, un processus, un type d'événement, une raison et un veto de
   l'arbitre, une section du prompt, une ressource réservée, une capacité deviennent une phrase française. Ce que
   déclarent les facultés est nommé par la **composition** (`app/console.py`, `Labels` : sections, raisons,
   vetos, processus, événements, facultés), comme la carte ; ce qui appartient au noyau et au runtime est nommé par
   la console. Une clé sans libellé reste lisible sous une forme générique (« Courrier · mail draft »), jamais un
   trou. Une issue se dit selon la sorte : une réponse, une initiative ou un murmure menés à bien « ont parlé » ;
   un travail, un journal ou un rêve est « terminé » (l'ancien « répondu » valait pour tout). Les clés techniques
   ne paraissent plus qu'au survol ou dans le détail d'une ligne. Le filtre « vers » des
   épisodes comprend un nom (« Adrien » vise toutes ses adresses) ; on confirme un oubli en retapant le **nom
   affiché**. Les erreurs se disent en français (`describe_error` : « délai dépassé », « fichier introuvable : … »),
   jamais en `repr`.
4. *Des nombres à la française* (`kernel/inspect.py`) : `num_fr` (« 0,42 », « 12 345 », « +0,22 »), `pct_fr`
   (« 42 % »), `money_fr` (« 0,0034 $ »), `day_fr` (« mer. 1 oct. ») — utilisés par le rendu de toute cellule
   réelle, par les courbes et par les pages de la console ; les facultés peuvent les adopter. Un champ dont le
   libellé porte déjà son unité (« Contexte (jetons) ») ne reçoit plus une unité devinée en plus ; « tokens » se lit
   « jetons », et une durée ne montre pas d'unité (elle se tape avec la sienne).
5. *Paginer juste.* `cursor_page` (noyau) est la brique commune des historiques à curseur : lus avec **N + 1**
   lignes, ils ne proposent « Plus anciens » que s'il y a une suite, et disent leur total quand il est connu (une
   première page sans suite). `InspectContext.older` la sert pour le journal ; la console l'adopte partout
   (tableau de bord, choix de l'arbitre, opérations, processus, approbations, chronologie, journal des
   modifications) ; le rendu dit aussi le total d'une première page sans suite pour les vues des facultés qui ne
   l'ont pas encore adoptée. Le journal des modifications est **une** requête filtrée en SQL. Toute valeur entière
   d'une requête (curseur, page, numéro d'événement) est ramenée dans [0, 2⁶³ − 1] (`int_query`) : plus de 500.
6. *Des badges qu'on éteint.* Un effet échoué ou orphelin de la file de sortie se **relance** (un essai de plus,
   tout de suite, confirmé) ou se **marque comme vu** (état `seen` : la ligne reste, le badge s'éteint) — audité.
   La chronologie ne lie à une page d'épisode que les corrélations d'épisode ; une action d'opérateur ou un effet
   mène à ses événements, et l'ancienne adresse d'épisode d'une telle corrélation y redirige.
7. *Rien ne part par erreur.* La touche Entrée déclenche le **premier** bouton d'un formulaire : il est désormais
   soit un « Enregistrer » caché, soit un bouton désactivé (une approbation : Entrée ne décide rien) ; les boutons
   secondaires d'un formulaire de paramètres appartiennent à un autre formulaire (`form=`). « Approuver » se
   confirme (la confirmation est portée par le bouton, pas par le formulaire : « Refuser » ne demande rien). La
   connexion à la console a le même étranglement que `/auth/login` (5 échecs par identifiant et IP par minute, 20
   par IP), et chaque échec se journalise. Une action d'opérateur écrit sous sa garde avec `basis` = ce qu'elle a
   lu (KER-28). Le jeton d'un formulaire ne se consomme qu'à une issue définitive (succès, refus) ; une panne ou une
   situation changée le rend, et l'audit d'une panne ne le porte pas.
8. *Des réglages qui refusent ce qui ne peut pas marcher.* Les choix connus d'une section (`SettingsSection.choices` :
   les fuseaux, UTC compris) s'appliquent à l'écriture, **import YAML compris** (sauf la valeur déjà en place). Un
   fuseau inconnu arrivé au journal par un ancien chemin ne casse plus rien : le noyau vit en UTC
   (`registry._zone`) et la santé le dit (contrôle « configuration lisible » : chaque faculté relit ses paramètres,
   le fuseau existe). Renommer une entrée d'une liste (un fournisseur) **emporte ce qui la désigne**
   (`forms.references` / `rename_references`, d'après `choices_from` : les rôles, le repli d'un autre fournisseur)
   et le dit ; retirer une entrée annonce, avant, ce qui ne pourra plus la désigner. Le nom d'une entrée suit une
   règle (lettres, chiffres, tirets, soulignés). Une liste dont des données hors du formulaire portent le nom (les
   boîtes aux lettres : leurs mails rangés) refuse d'être renommée (`fixed_names`), en le disant. Un fournisseur
   n'est **interrogé que sur le bouton** « Charger la liste », qui n'enregistre rien — afficher sa page ne coûte plus
   un appel réseau. L'adresse de transcription, les hôtes git, l'utilisateur git et le nom de la persona sont
   validés ; un robot Telegram sans liste blanche est signalé en tête de sa page.
9. *« Que ferait-elle maintenant ? »* (Décisions › Que ferait-elle ?) : pour une personne, ses lignes de l'arbitre,
   ce qui la pousse, ce qui la retient (veto, seuil), et dans combien de temps elle agirait en moyenne — en lecture
   seule. La fiche d'une personne y mène (« maintenant »).

**Conséquences.** Les identifiants techniques restent consultables (survol, détail, « Détails techniques ») : rien
n'est perdu pour qui débogue. La table des libellés vit dans la composition : une faculté qui ajoute une raison,
un veto, une section ou un processus devrait l'y nommer ; sans quoi elle se lit sous sa forme générique. La page
d'un fournisseur ne charge plus d'elle-même la liste de ses modèles (contrairement à l'ADR 0029) : c'est le prix
d'une page qui s'ouvre sans attendre un réseau. Relancer ou marquer comme vu passe par `mark_outbox`, qui compte
un essai de plus : la colonne « essais » d'une ligne relancée compte aussi la relance. Un ancien journal se rejoue à l'identique : aucun événement,
aucune tranche ni aucun paramètre n'a changé de forme. Tests : `test_console_operator.py` (page « pourquoi » liée
depuis le fil, noms et filtre par nom, oubli par le nom affiché, étranglement de la connexion, touche Entrée,
fuseau inventé refusé puis sans effet, renommage qui emporte les rôles, boîte au nom fixe, validations, journal
des modifications sans perte, chronologie, relancer et marquer comme vu, curseurs géants), `test_console_why.py`
(le bon choix de l'arbitre, prélude compris), `test_console_names.py` (formats, erreurs, issues selon la sorte,
curseurs, références),
`test_operations.py` (garde avec `basis`, jeton rendu à une panne), `test_console_pagination.py` (total d'une
première page, jamais d'une page numérotée plus loin).
