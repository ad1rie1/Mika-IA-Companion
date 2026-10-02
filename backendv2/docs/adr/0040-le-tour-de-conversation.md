# 0040 — Le tour de conversation, la parole qui n'attend pas, des boucles sûres

**Contexte.** L'audit du noyau (KER, PRM P1–P2, EDG-7/13, PRJ-5/25, CON-17) a trouvé un runtime correct sur le
chemin heureux et fragile partout ailleurs :

- *Une réponse par message.* « salut », « t'as vu le match ? », « allo ? » en deux secondes donnaient trois réponses
  (+10, +20, +30 s), la première composée sans savoir que la personne avait écrit deux fois de plus ; une réponse
  supplantée était recomposée **après** la réponse au message suivant.
- *La parole attendait.* Une réponse passait derrière une initiative elle-même bloquée par un long pas de fond sur un
  modèle local à un créneau (+85 s au lieu de +7 s) ; une livraison attendait la fin d'un `git push` ou d'un
  `npm install` dans l'unique file de sortie (+89 s) ; un envoi Telegram raté n'était réessayé qu'au prochain
  énoncé, et après une panne la file livrait les réponses de la veille.
- *Des artefacts livrés.* « [trop d'appels d'outils : j'arrête là] » partait comme sa parole ; `**[SILENCE]**`,
  `(silence)` ou « bon, je vais rien dire. [SILENCE] » aussi.
- *Des boucles sans fin.* Un processus dû « maintenant » qui lève (l'index de vecteurs sans son extra) écrivait
  6 912 événements en deux secondes ; un processus dû qui ne fait rien était relancé sans arrêt ; un gestionnaire
  d'effet fautif tuait la file de sortie à chaque démarrage ; une tranche non sérialisable bloquait toutes les
  écritures ; une purge d'oubli qui lève empoisonnait l'écrivain ; retirer un plugin rendait le journal illisible ;
  à l'heure d'hiver un agenda `cron` tournait en boucle une heure. (Le 2026-10-02, une épreuve qui retirait le recul
  de l'ordonnanceur a pris 23 Go et tué la machine : une boucle sans pause, journalisée à chaque tour.)
- *Des épisodes jamais réglés*, la vie démarrée avant la passerelle et Telegram, un murmure qui partait avant que
  l'initiative soit seulement admise.

**Décision.**

1. *Le tour.* Les messages d'une adresse en un lieu (`(adresse, salon)`) encore sans réponse forment son tour
   (`runtime.turn`). La demande de réponse en file d'un tour se met à jour au lieu de s'empiler (une seule réponse,
   au dernier message) ; la garde `tour` d'une réponse exige que `reply_to` soit toujours le dernier message du tour —
   un nouveau message la supplante, elle est recomposée en le lisant (le fil, coupé avant `reply_to`, montre les
   précédents). L'énoncé règle tout le tour (`Utterance.answers`) ; une fin sans parole dit ce qu'elle laisse sans
   réponse (`EpisodeEnded.unanswered` : elle s'est tue, la réponse a échoué, les tentatives sont épuisées, trop
   tard) — une intention journalisée ; un journal plus ancien se relit avec l'ancienne règle. La tranche du runtime
   passe en version 2 (une question sait son salon). Une reprise (panne, supplantation) répond au dernier message du
   tour, une fois ; la première tout de suite, les suivantes espacées (½ s, 1 s… 30 s) ; au-delà de dix minutes,
   le tour est abandonné en le disant.
2. *La nuit compose avec le tour* (`KernelDeps.reply_wait`, ADR 0036). Un message qui ne l'a pas réveillée n'ouvre
   pas d'épisode ; au réveil, chaque tour qui attendait reçoit **une** réponse, à son dernier message, qui règle les
   précédents (« lus avec lui ») — plus d'abstention fictive pour les messages d'avant, et un tour privé n'est jamais
   réglé par une réponse dans un salon. Si la personne l'a réveillée elle-même, la réponse à ce message-là lit déjà
   toute sa nuit. Une réponse supplantée dont le tour s'est entre-temps endormi attend le réveil au lieu de partir.
   L'âge d'une question de la nuit compte depuis son réveil — et, si elle n'était pas là pour la lire au matin (un
   arrêt du serveur), depuis son retour (`live`) : ce qui l'attendait au matin lui est encore dû. Une question du
   jour compte toujours depuis qu'elle a été posée.
3. *Une réponse impossible se dit, sans voix.* Un tour laissé sans réponse part au transport par la file de sortie,
   au contrat des bords (ADR 0038, `ports/delivery.py`) : `Delivery(kind="reply_abstained")` quand elle a choisi de
   se taire, `Delivery(kind="reply_failed", text=<détail technique>)` sinon (échec, délai, tentatives épuisées,
   trop tard), avec `target`, `channel`, `room`, `reply_to=<dernier message du tour>`, `client_msg_id` et
   `source=<issue>`. Une livraison par tour, pour son dernier message : le web passe la bulle en échec ou éteint
   « Mika écrit… » (une fois par question, qu'il l'apprenne par là ou par l'attente de la connexion) ; Telegram
   n'écrit son « désolée » qu'une fois. Une réponse reprise au démarrage, que personne n'attend plus, est couverte.
4. *La parole n'attend pas.* Une demande de premier plan qui trouve sa voie pleine d'épisodes moins prioritaires
   en désigne un pour céder (`preempted`) : tout de suite s'il attend le modèle, sinon avant tout appel — jamais au
   milieu d'un règlement ni pendant l'écriture de son énoncé. L'arbitre le reproposera. Le simulateur le tient en
   cible (S22 : une réponse part en moins de 15 s quand un pas de 90 s tient le modèle et qu'une initiative attend).
5. *Deux files de sortie.* `delivery` (la parole, les états) : dans l'ordre de chaque (gestionnaire, destinataire),
   les destinataires en parallèle ; `capability` (les effets sur le monde) : une tâche par ligne, en parallèle borné.
   Chaque gestionnaire a son échéance. Un échec (levée, échéance, ou `False` du transport — le routeur le rend quand
   le canal n'est pas là ; `expression` n'a pas à lire ce retour, la file le voit) est réessayé à une date, avec
   recul (5 s, 10 s… dix minutes), puis abandonné (`failed`) ; une parole qui n'a pas pu partir dans les dix minutes
   ne part plus (`stale`). Un compte rendu refusé (un bogue) clôt la ligne sans la rejouer. Une capacité est
   marquée « en cours » avant de partir : après une panne, une capacité non rejouable (`idempotent=False`, le
   défaut) n'est pas relancée — son échec est journalisé (`effect.executed`, « interrompue par un arrêt »).
6. *Jamais un artefact.* Au plafond de tours d'outils, ou quand un appel reste coupé, un dernier tour sans outil
   lui demande de répondre avec ce qu'elle sait (la requête finit par les résultats d'outils puis ce mot de
   l'utilisateur : la forme qu'une session CLI sait finir) ; sans texte, l'épisode échoue. Le silence est reconnu
   sous ses formes réelles (balise entre crochets où qu'elle soit, normalisée ou non, le seul mot *silence* nu ou
   entre parenthèses), jamais un vrai message qui contient le mot. Toute boucle de modèle finie — réponse, plafond,
   coupure, annulation — est relâchée (`release(call_id)`), et l'appel d'un processus dès son retour : un fournisseur
   à session n'attend pas son fauchage à 660 s.
7. *Toujours réglé, une fois.* Une exception imprévue règle l'épisode en `failed` ; le règlement est idempotent
   (plus de second `superseded` derrière une abstention) ; un bail pris en route est rendu.
8. *Des boucles sûres, par construction.* Un processus en échec recule (5 s doublés jusqu'à une heure), un seul
   `process_failed` par série. Un passage qui n'a rien écrit — un ajout entièrement dédoublonné ne compte pas — et
   se redit dû sur-le-champ, sans que rien de ce qui le réveille n'ait bougé, attend 30 s, puis 1 min, 2 min…
   jusqu'à une heure ; un processus qui se donne une échéance à venir (un agenda, un relevé qui n'a rien trouvé)
   n'est pas concerné. Et quoi qu'il fasse, plus de 120 passages d'un même processus en une minute font une
   *rafale* : il est retenu une minute, puis deux, quatre… (la santé le montre). Le calcul pur ne tient aucune
   place : seuls les appels de modèle des processus passent par la voie bornée `model` ; `night` reste exclusive.
   Chaque passage a une échéance. Un instantané se fait au mieux (une tranche qu'on ne sait pas sérialiser en est
   tenue hors et se reconstruit depuis la genèse, l'aller-retour de chaque tranche est vérifié au démarrage). Une
   garde qui lève supplante son épisode au lieu de faire échouer l'ajout d'autrui. Les transactions SQLite défont
   tout ce qu'elles ont commencé (une validation qui échoue comprise) ; l'oubli ne fait plus de `VACUUM` (pages
   mises à zéro par `secure_delete`, WAL tronqué). Un type d'événement que plus personne ne déclare se relit
   « retiré ». Deux effets d'une même faculté sur un même type sont refusés à la composition. L'agenda `cron` rend
   toujours un instant futur, l'heure qui revient à l'automne comprise. Les épreuves de ces boucles s'arrêtent
   d'elles-mêmes au-delà de 2 000 passages : un emballement fait échouer le test, il ne tue plus la machine.
9. *Démarrage en deux temps.* `Kernel.boot` (relire, configurer) puis `Kernel.live` (voies, reprise, processus,
   file de sortie) ; le serveur branche passerelle, budget, comptes, écrans et Telegram entre les deux.
10. *Le murmure* (le prélude d'une initiative) est décidé une fois, au départ gardé de l'épisode. Ordinaire, il passe
   une fois la réponse de l'initiative prête, sous sa garde (et tant qu'elle n'est ni devancée ni désignée pour
   céder) : une initiative devancée ne laisse pas de murmure orphelin. *Sans suite* (`Prelude.instead` : elle y
   pense, puis se ravise), il passe aussitôt, seul, et l'initiative se règle (`abstained`, « elle s'est ravisée »)
   **sans être composée** — aucun appel de modèle pour une parole qui ne partira pas.
11. *Ce qui est en main.* Une réponse ordinaire a en main la mémoire et les rappels ; le reste est offert à la
   demande. Un candidat qui a choisi ses lots (un pas, une exécution) les a tous en main.
12. *Divers.* `episode.started.selected` porte le numéro exact de la sélection (la console le montre) ; une écriture
   d'outil est dédoublonnée par ce qu'elle est dans le tour (outil, arguments, occurrence), jamais par l'identifiant
   d'appel du fournisseur ; une envie « ANY » est partagée entre les présents (huit présents n'octuplent plus son
   taux).

**Conséquences.** S21 (une rafale, une réponse qui a tout lu ; deux tours séparés, deux réponses) et S22 (la
réponse sous charge) rejoignent la voie rapide ; S13 compte une question réglée par `answers` ou `unanswered`. Les
tests du runtime (`test_conversation_turn`, `test_latency_outbox`, `test_runtime_robustness`) cassent sur l'ancien
code, et chaque correction importante a été vérifiée en la cassant exprès (copie jetable, source restaurée). Les
cibles de la nuit (`test_sleep_body`) disent désormais « une réponse qui règle le tour » plutôt que des abstentions.
Contrats : `EpisodeStarted.selected`, `Utterance.answers`, `EpisodeEnded.unanswered` (défauts : le journal se
rejoue) ; tranche `runtime` v2 ; fait `runtime.turn` ; `Prelude.instead` ; `EffectSpec.lane / deadline_s / when /
on_interrupted` ; `CapabilitySpec.idempotent` ; `ProcessSpec.deadline_s`. Reste ouvert : l'ordonnanceur recalcule
toujours toutes les échéances à chaque réveil (un cache selon `wake_on` changerait ce que voient les processus qui
lisent d'autres tranches sans le déclarer), et les traces d'épisode passent encore par l'unique fil d'écriture
(une file séparée pour `views.db`).
