# 0106 — Ce qu'on lui envoie : gardé, lu de près, relié à ce qu'elle sait

**Contexte.** Le 2026-10-13, la propriétaire demande qu'une photo ou une pièce jointe envoyée dans un chat soit
analysée et **gardée** ; qu'il puisse y avoir un lien entre un fait, une pièce jointe et un souvenir ; que tout cela
reste accessible par le MCP de Mika, pour chercher et ouvrir les fichiers.

Ce qui existait : au bord, une pièce jointe était perçue (`ports.preprocess` : une photo décrite en deux ou trois
phrases par le rôle `caption`, un PDF ou un texte lu, un vocal transcrit), ce texte collé au message, puis **les
octets jetés**. Le message gardait un nom et une sorte (`AttachmentMeta`). Rien ne permettait de revoir la photo,
de relire un long document au-delà de 8 000 caractères, ni de savoir de quelle pièce venait ce qu'elle en avait
retenu.

**Décisions de la propriétaire.**
- *Un lien n'est pas une source* (« source n'est pas un fichier : c'est en plus, et il peut y en avoir plusieurs »).
  Les `sources` d'un souvenir, d'une croyance, d'un moment restent des messages ; ses pièces sont un champ de plus,
  plusieurs-à-plusieurs.
- *Un seul MCP* : ses outils (son jeu unique, servi par le relais à la CLI Claude Code, en natif aux autres
  fournisseurs). Pas d'outil à part dans la console MCP.
- *Devant qui* : la règle graduée de sa mémoire.
- *La place* : 2 Gio par personne, avec ce que chacun consomme visible.

**Décision.**

1. *Gardée au bord.* Avant de soumettre le message, le bord web garde les octets de chaque pièce par le port
   d'entrée (`MindPort.keep_attachments`) dans le port `attachments` — un dossier `pieces/` du dossier de données, la
   même forme que `partages/` (ADR 0062) : un fichier par pièce, 0700/0600, sauvegardé et restauré avec lui. La clé
   d'une pièce (`file_id`) dépend de l'adresse et des octets : la même photo renvoyée par la même adresse est la même
   pièce, portée par deux messages ; une autre adresse en a une autre (oublier l'une n'efface pas la pièce de
   l'autre). Le message la désigne : `AttachmentMeta.file` (champ ajouté, vide pour un message d'avant).

2. *Lue de près, en fond.* Nouvelle faculté `attachments`. Sa tranche note chaque pièce désignée **à lire** ; le
   processus `attachments.study` la lit sans presse, la plus ancienne d'abord, par le port `preprocess`
   (`Preprocessor.study`) : une photo décrite en détail par le modèle qui voit (rôle `caption`, voie de fond), son
   texte visible recopié, et une ligne « INTIME : oui/non » que le code lit puis retire ; le texte entier d'un
   document (200 pages, `text_max_chars`) ; la transcription d'un vocal. Puis `attachments.kept` : le nom et ce
   qu'elle y a lu sont des **contenus** (effaçables, sujets : l'adresse et la personne derrière). Sensibilité :
   personnelle en privé, anodine dans un salon public, **une confidence** quand la lecture l'a jugée intime (nudité,
   santé, papiers, banque). Un échec passager (modèle injoignable, délai) se redemande, trois fois au plus, à 5 puis
   10 minutes ; au-delà, la pièce est gardée sans lecture (son nom seul). Des octets absents quand il faut la lire
   (oubliée entre-temps) : `attachments.expired` raison `missing`, rien n'est écrit. « Regarder de près les images
   reçues » se décoche (un appel de modèle par image).

3. *Trois projections T0.* `received_files` (une ligne par pièce lue, avec un texte replié pour la recherche par
   mots), `received_messages` (quel message porte quelle pièce, à quelle place), `received_links` (pièce ↔ élément,
   qui l'a relié, quand). Un index de vecteurs **à part** (`attachment_vectors`, même modèle de plongements) : le
   rapprochement de l'index de la mémoire retire toute clé qui n'est pas à elle. Un vecteur par pièce : son nom, le
   début de ce qu'elle y a lu, et ce qu'elle sait qui y est relié (hors secrets), refait quand un lien change.

4. *Les liens.* La relecture voit, après chaque message qui en porte, les repères de ses pièces
   (`[pièces : #12.1 « chat.jpg » (photo)]`) et désigne pour chaque souvenir, croyance ou moment celles d'où il vient
   (`pieces`, un repère ou un nom) — plusieurs au besoin. `memory.remembered`, `believed`, `event_noted`,
   `reinforced` et `attested` portent `pieces` (des clés, pas des mots), **à côté** de `sources`. Sans désignation,
   un seul cas se lie d'office : les messages que l'élément cite ne portent qu'une pièce (un petit modèle oublie les
   champs facultatifs) ; parmi plusieurs, rien ne se devine ; un élément qui ne cite rien ne se lie pas. La
   projection ne relie que des pièces que des messages ont réellement portées : une clé inventée ne relie rien. Plus
   tard, elle relie elle-même (`attachment_link`, `attachments.linked`) : en mots — l'outil cherche l'élément par le
   sens dans sa mémoire, le plus proche s'il l'est assez et qu'il peut se dire ici —, et délie de même.

5. *Ses outils* (lot `attachments`, à la demande, dans les réponses, les initiatives et les séances de travail) :
   `attachments_search` (par le sens et les mots, de la personne à qui elle parle ou de tous, d'une sorte ; sans
   question, les plus récentes ; chaque ligne dit ce qui y est relié), `attachment_open` (ce qu'elle y a lu, cité,
   page par page ; une photo se regarde de nouveau pour une question, `Preprocessor.look`, voie de la conversation ;
   ce qu'elle sait qui va avec), `attachment_link`. Les repères (le début de la clé) ne servent qu'à ses outils et ne
   se disent jamais en conversation. Elle ne renvoie jamais une pièce reçue (ADR 0062).

6. *Devant qui.* Le verdict commun (`vocab.lineage.admits`, celui de sa mémoire) : une pièce est confiée par son
   expéditeur, entendue par lui seul en privé. Elle la rouvre devant lui (fiche ouverte), dans le salon où elle a été
   postée, pour elle-même (une séance de travail, une pensée) ; devant quelqu'un d'autre seulement si la règle des
   liens le permet (une proche liée à la personne, jusqu'au niveau de la pièce) — jamais une pièce privée dans un
   salon public. Ce qui y est relié passe par le même verdict, élément par élément.

7. *La place et l'oubli.* Gardée pour toujours par défaut (`keep_days` 0), dans 2 Gio par personne
   (`per_person_mb`, toutes ses adresses réunies) : au-delà, les plus anciennes sont retirées (`attachments.expired`,
   raison `budget`) — leurs octets s'effacent après le commit, ce qu'elle en avait lu et ses liens restent. Oublier
   une personne efface ses octets (le port, par ses sujets), ses lignes, ses contenus, ses liens et ses vecteurs.

8. *La console.* Mémoire › Pièces reçues (recherche, sorte), Mémoire › Place des pièces (ce que chacun occupe face à
   sa place, une jauge), un onglet « Pièces reçues » sur la fiche d'une personne, et la fiche d'une pièce (ce qu'elle
   y a lu, ses liens, les messages qui l'ont portée, téléchargement). La console MCP les sert d'office (vues et
   fiches), en lecture seule.

**Ce qui n'est pas fait.** Les clients (web, Android) ne montrent pas encore une pièce envoyée comme téléchargeable
par son expéditeur dans l'historique. Les pièces jointes des mails restent au courrier. Un document n'a pas de
jugement « intime » (il est personnel en privé). Une pièce lue avant que la vision soit branchée ne se relit pas
d'elle-même.

**Vérifié.** `tests/unit/test_attachments.py` (14 cibles, cinq mutations tuées : la règle de qui rouvre, le « ne
devine pas parmi plusieurs », la clé inventée, l'oubli des liens, la confidence d'une photo intime) ;
`tests/protocol/test_senses_web.py` (une photo envoyée par le WebSocket est dans `pieces/`, désignée par son
message, et attend sa lecture).
