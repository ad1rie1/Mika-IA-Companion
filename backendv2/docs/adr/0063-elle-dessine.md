# 0063 — Elle dessine

**Contexte.** L'ADR 0061 a branché des fournisseurs d'images (OpenAI, son serveur local stable-diffusion.cpp,
tout serveur compatible) derrière le port `imaging`, désactivé tant que rien n'est branché ; rien ne s'en servait.
L'ADR 0062 a donné à Mika des fichiers à envoyer : les octets dans le port `shares`, hors du journal, et un fichier
qui part **avec** un message (`ToolResult.attach` → `Utterance.attachments` → la trame, `/files/<id>` pour le seul
compte dont le fil le porte). Il manquait le cas d'un fichier qui prend des minutes à naître. La propriétaire a
décidé (2026-10-04) : en conversation, un brouillon par défaut, la qualité haute seulement si on la demande, le tout
réglable ; des garde-fous pour les personnes extérieures seulement (pas pour elle), au-dessus d'un plancher légal
commun ; des dessins pour les personnes qui ont un compte.

**Décision.**

1. *Un plugin, `imaging`* (`plugins/imaging/`), contrat `contracts/imaging.py` : `imaging.requested` (le prompt
   qu'elle a écrit, un contenu effaçable ; proportion, qualité, adulte, demande de la propriétaire),
   `imaging.drawn` (public), `imaging.failed` ; un fait `imaging.status(job)`. La tranche suit chaque dessin : en
   cours, prêt, montré, raté, raté et dit.
2. *Demander* : l'outil `draw`, offert dans une réponse et cherché à la demande comme le reste (une réponse ordinaire ne porte pas tous ses outils d'emblée ; le catalogue dit « dessiner pour la personne »). Elle écrit elle-même le prompt — en anglais, détaillé, le
   décor d'abord, le cadrage dit (un modèle d'images suit mieux une description précise que la demande brute) — et
   choisit la proportion. L'outil répond tout de suite (« c'est lancé, deux ou trois minutes ») : elle dit qu'elle
   s'y met, sans décrire une image qu'elle n'a pas vue.
3. *Dessiner* : le processus `imaging.draw` prend le plus ancien dessin en cours, le fait générer par la passerelle
   (ses fournisseurs, replis, créneaux ; un refus pour sa propriétaire peut repartir vers le serveur local), dépose
   les octets dans le port `shares` (sujets : la personne), **le regarde** (rôle « décrire une image ») pour pouvoir en
   parler, puis journalise `imaging.drawn` — ou `imaging.failed` avec la raison. Un passage dure ce que dure l'image ;
   les processus tournent chacun dans leur tâche, il ne retient personne. Coupé, le dessin reste « en cours » et le
   passage suivant le reprend.
4. *Un seul chemin d'envoi* : `imaging.drawn` dérive de `shares.ProducedFile` (nouvelle forme du contrat de
   `shares`) ; la faculté `shares` le range comme ses fichiers (origine `drawn`, sorte `image`) — même ligne dans
   `shared_files` (version 2), même départ avec un message, même rétention, même oubli — sans le compter dans son
   quota de fichiers (les dessins ont le leur). Un fichier jamais parti est désormais retiré au bout de
   `unsent_days` (7 jours) plutôt qu'un an.
5. *Montrer* : `show_drawing` (sans identifiant à recopier : le plus ancien dessin prêt pour la personne de
   l'épisode) rend `attach`, et le message qui suit l'emporte. Deux occasions : la section « TES DESSINS » de sa
   réponse quand la personne écrit entre-temps (« il est prêt — ce que tu y vois : … — montre-le avec
   show_drawing ») ; sinon l'**initiative due** `drawing_ready`, vers là où la personne est (connectée, sinon
   joignable, sinon l'adresse de la demande), avec le lot `imaging` en main et une garde qui l'annule si le dessin a
   été montré entre-temps. Un échec se dit de même (`drawing_failed`). Les deux entrent dans `agency.OWED` : comme un
   rappel, ce n'est pas prendre la parole (ni plafond du jour, ni période réfractaire).
6. *Qui* (`plugins/imaging/policy.py`) — **le plancher**, pour tout le monde, propriétaire comprise, non réglable :
   rien de sexuel avec un mineur (des mots et des âges, en français et en anglais), rien de sexuel avec une personne
   réelle (ce qu'elle déclare de la demande). C'est un plancher sur ce qu'elle écrit, pas une garantie : le modèle
   d'images n'a aucun filtre. **Au-dessus** : l'outil n'est offert qu'en tête-à-tête, à sa propriétaire ou à une
   personne authentifiée — jamais dans un salon, jamais à un inconnu ; la propriétaire sans quota, le contenu pour
   adultes seulement pour elle et seulement vers un fournisseur qui l'accepte ; une personne authentifiée : un quota
   par jour (`per_day`, 5) et des dessins en cours bornés (`max_waiting`, 2).
7. *Réglages* (Comportement › Dessins) : qualité par défaut (brouillon), qualité haute permise, quota par jour,
   dessins en cours, la regarder une fois finie, la force de l'initiative due, le délai au-delà duquel un dessin
   n'est plus annoncé. Console : Sens › Dessins (où chaque dessin en est, ce qu'elle a écrit, ce qu'elle y voit, le
   coût).
8. *L'écran web* (`frontend/Web`) affiche les fichiers d'un message de Mika : un dessin en vignette (un clic l'ouvre),
   un autre fichier en lien, « plus disponible » une fois retiré ; seule une adresse exactement `/files/<id>` est
   acceptée (`chatSync.sentFiles`). L'application Android les affichait déjà.

**Conséquences.** Rien ne change pour une installation sans fournisseur d'images (l'outil répond qu'elle ne peut
pas dessiner, sans rien journaliser). Le serveur local ne sait pas interrompre une génération commencée : un dessin
de fond fait attendre une demande jusqu'à sa fin. Épreuves : `tests/unit/test_imaging_plugin.py` (le plancher, qui
peut demander, quotas, qualité, le parcours complet jusqu'au téléchargement, l'échec dit, l'initiative due) ;
cinq règles cassées exprès (la section témoin, le quota de la propriétaire, l'adulte d'une personne extérieure,
« montré » par l'énoncé, le plancher des mineurs) font chacune échouer leur test ;
`frontend/Web/src/ui/__tests__/sentFiles.test.ts`.
