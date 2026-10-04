# 0056 — Le fil, le chat et ce que voit la personne

**Contexte.** Un audit des interfaces (2026-10-03, lecture seule) a branché un serveur v2 neuf sur un client qui
imite le frontend web (`frontend/Web/`), trame par trame. Le protocole était aligné (les 29 émotions, les phases, les
statuts d'`ack`), mais ce que voyait la personne ne l'était pas : un navigateur passé de l'ancien moteur à v2 cachait
les messages de v2 derrière son cache ; le frontend visait encore le port de l'ancien moteur ; une réponse ratée
rayait le message de la personne comme s'il n'était pas parti ; sans modèle, tout le monde lisait une commande
d'administration dite par Mika ; le fil rechargé montrait le contenu des pièces jointes avec le jargon du prompt ; la
nuit, rien ne disait qu'elle dormait ; et le panneau parlait en identifiants (`full`, `manual`, `email.send`,
`authenticated`).

**Décision.**

1. *Le fil d'une autre vie ne cache plus celle-ci (B-1).* L'ancien moteur numérotait les messages par la clé de sa
   base, v2 par le `seq` de son journal, qui repart de quelques dizaines — sous la même clé de cache (`user_<n>`) :
   le curseur de l'ancien fil cachait le nouveau et ses identifiants passaient pour connus. Deux gardes, une par
   côté :
   - chaque trame `history` porte l'**empreinte de sa vie** (`life` : un condensé de l'identifiant du premier
     événement du journal, `MindPort.life()`), la même tant que c'est le même journal — une sauvegarde restaurée
     comprise —, une autre pour un autre dossier de données ;
   - un `sync` dont le curseur dépasse la tête du fil de cette adresse (une sauvegarde plus ancienne restaurée, un fil
     oublié, des identifiants d'ailleurs) reçoit le **fil initial** marqué `reset: true` au lieu d'un rattrapage vide.

   Le frontend garde l'empreinte avec son cache (`{life, messages}`, `chatSync.readCache` lit encore l'ancien tableau
   nu, d'une vie inconnue) ; sur `reset`, ou une empreinte qui n'est pas celle du cache — un cache sans empreinte
   compris —, il vide ce qu'il montre avant de fusionner, sauf les messages de cet onglet encore en partance. Un
   serveur qui ne donne pas d'empreinte ne fait rien vider. La première ouverture après la mise à jour vide donc
   une fois les caches existants (le fil initial les remplace ; les pensées murmurées, qui ne sont qu'à l'écran,
   sont perdues cette fois-là).

2. *Le frontend vise v2 (B-2).* Défaut `http://localhost:8001` (`network/api.ts`, `WebSocketClient`), un
   `frontend/Web/.env.example` qui documente `VITE_BACKEND_ORIGIN` (l'ancien moteur : 8000), et des messages d'erreur
   qui disent quoi faire en v2 (`python -m mika serve --origin <cette page>`) au lieu de `CORS_ALLOWED_ORIGINS`.

3. *Une réponse ratée ne raye plus le message (G-1).* Le second `ack` d'une question **reçue** dont la réponse ne
   viendra pas est `no_reply`, avec sa cause en un mot (`reason` : `no_model`, `unreachable`, `timeout`,
   `too_late`, `error`, lue dans l'issue de l'épisode et son détail, `protocol.no_reply_reason`). La bulle reste
   « envoyée » — elle l'est —, une note dessous dit « Mika n'a pas pu répondre — réessaie » (« … à temps — redis-le-lui
   si c'est encore d'actualité » pour une question reprise trop tard). `overloaded` ne dit plus que ce qu'il dit :
   une file pleine, un message non reçu. `too_late` devient une cause de `no_reply` ; le frontend lit encore
   l'ancien statut.

4. *La consigne d'administration n'est dite qu'aux opératrices (G-5).* Sans modèle, plus aucune phrase « de Mika »
   (la pensée « python -m mika llm … » est supprimée). Une connexion opératrice reçoit dans son `ack` la cause en
   clair (`detail`) et où la réparer (`href`, `/inspecteur/reglages/fournisseurs`) : une note de la machine sous la
   bulle, avec un lien vers la console (le client n'accepte qu'une page `/inspecteur/…`). Les autres n'ont que la
   note du point 3. Le sort se règle désormais connexion par connexion (`Hub.settle_reply`).

5. *Le fil relu montre ce que la personne a tapé (G-6).* Le texte d'une perception reste le corps perçu (ce qu'elle a
   tapé, puis ce que ses pièces jointes ont donné : il nourrit le prompt, la mémoire, l'attention). Un champ de la
   perception dit où s'arrête la part tapée (`PerceptionReceived.typed_chars`, `None` par défaut : rien à séparer)
   et le fil le garde (colonne `typed`, table `thread` en **version 2** : elle se reconstruit depuis le journal au
   premier démarrage). `history` envoie la part tapée et les fichiers par leur nom et leur sorte ; le frontend les
   affiche `texte [photo.png]` comme à l'envoi (`chatSync.withAttachments`, la même composition des deux côtés,
   d'où une adoption par égalité exacte : la règle de préfixe disparaît). Un message d'un journal plus ancien, sans
   séparation connue, garde son affichage (texte perçu, aucune pièce jointe annoncée). La console montre toujours
   le texte perçu : c'est ce qu'elle a lu.

6. *Elle dort, et le chat le dit (G-10).* Une trame `speech` sans texte, `voice_reason: "asleep"`, pose sous la bulle
   « Mika dort — elle te répondra à son réveil », tant qu'elle n'a rien dit depuis (sa réponse au réveil, même
   arrivée par un rattrapage, la rend caduque ; un murmure, non).

7. *Le panneau parle français.* v2 envoie les libellés : le mode d'un projet (`mode_label` : rien pour le sien,
   « impersonnel » pour un travail factuel), son agenda comme la console le dit (`schedule_label` : « les jours
   ouvrés à 9 h », « toutes les 45 min »), et pour ce qui attend un accord à qui c'est (`owner_label` : le projet,
   « Courrier », « Forge ») et ce que ça fera (`kind_label`, la description de la capacité) ; « Ce qui attend ton
   accord ». Le journal montré est celui d'une journée passée : son titre le dit (`today_journal.title`, « Son journal
   d'hier »), jamais « d'aujourd'hui ». Le frontend traduit la confiance du transport, ne cite une preuve que s'il
   y en a une, ne montre plus un « ton : » vide, nomme les besoins avec les mots de la console (« Besoins :
   Compagnie, S'exprimer, Apprendre », confronté par un test à `faculties/needs/inspect.py`), retire le gestionnaire
   mort `project_report` et les champs vides du récit de soi, et borne le champ de saisie à 2 000 caractères (un
   compteur à l'approche). « Un compte existe déjà » prend son accent ; l'écran de connexion lit le statut 409,
   plus la phrase.

**Conséquences.** Contrat : `history` gagne `life` et `reset` ; ses `attachments` deviennent `{name, kind}` et son
`text` la part tapée ; `ack` gagne le statut `no_reply` et `reason` (et, pour une opératrice, `detail`, `href`) ;
`inner_state` gagne `mode_label`, `schedule_label`, `owner_label`, `kind_label`, `today_journal.title` et perd les
champs vides de `self_narrative`. `MindPort` gagne `life()`. Le journal existant se rejoue : `typed_chars` a un
défaut, la table `thread` se reconstruit (nouvelle version). Un client plus ancien lit `no_reply` comme un refus
(son comportement pour un statut inconnu) : client et serveur vont ensemble.

**Reste.** Un menu opératrice dans le frontend (console, déconnexion, « pourquoi a-t-elle dit ça ? » sur une bulle),
et un bouton « réessayer » sous une réponse qui n'est pas venue.
