# 0068 — Les réveils par API

**Contexte.** Rien ne permettait à un système extérieur (un script, une domotique, une CI, une alerte) de **faire agir**
Mika. `POST /api/perceptions` (plugin `sensors`) dépose un signal cité dans son attention : il peut colorer son humeur
ou, des heures plus tard, faire naître une exploration, mais jamais un travail tout de suite. Le seul jeton de ce
point est global, et le nom de l'appareil est ce que l'appelant déclare. La propriétaire a demandé (2026-10-06) des
**réveils** : plusieurs points d'entrée, chacun avec sa terminaison d'URL et sa clé, qui portent un texte servant de
base à son travail. Pour chacun : un projet, le mode impersonnel, des outils, des consignes prioritaires sur le texte,
et « ignorer le rythme circadien ». Elle a tranché quatre questions :

- impersonnel veut dire le mode `JOB` des projets ;
- ce qu'elle produit est un travail silencieux, puis une initiative vers une personne (sa propriétaire par défaut) ;
- l'authentification est une clé générée par réveil ;
- « ignorer le rythme » la réveille vraiment, comme le message d'une proche.

**Décision.**

1. **Un plugin `wakeup`, et la porte hors de lui.** Un plugin n'a pas de route : la route est dans le transport web
   (`POST /api/wake/<nom>`, `adapters/web/app.py`). Elle passe l'appel à une **porte** (`ports/wakeup.WakeGate`,
   implémentée par `app/wakeups.WakeupDesk`), qui décide **avant** que quoi que ce soit soit journalisé :
   - un réveil inconnu et une mauvaise clé reçoivent la même réponse (401), avec une comparaison en temps constant
     dans les deux cas ;
   - trop d'échecs d'une même adresse IP : 429 ;
   - un réveil désactivé : 403 ; un texte vide ou trop long : 400 ;
   - trop d'appels, dans l'heure ou en attente : 429 avec `Retry-After` ;
   - son projet n'est pas actif : 409 ;
   - reçu : 202 `{ok, call}`.

   Une `Origin` inconnue est refusée, le corps est borné, toute réponse porte `no-store`. Une `Idempotency-Key` sert
   de clé de dédoublonnage : rejouée, elle rend le même appel.
2. **Ce que l'opérateur déclare** (Configuration › Plugins › Réveils par API, `app/wakeups.WakeupConfig`), un
   enregistrement par réveil. Le nom est la fin de l'URL : il ne change plus une fois créé. Chaque réveil porte :
   - à quoi il sert (obligatoire) et s'il est actif ;
   - des consignes, et un projet (ou aucun) ;
   - le mode impersonnel, et ses outils (des lots : `memory`, `email`, `rss`, `camera`, `forge`, `forge_apps`,
     `mcp.<serveur>` ; aucun par défaut) ;
   - s'il passe outre son sommeil, et à qui il rend compte (ses propriétaires, un compte actif, personne) ;
   - des bornes : appels par heure, appels en attente, durée de vie d'un appel, longueur du texte.

   L'enregistrement vérifie que le projet, la personne et les lots existent ; un champ d'enregistrement peut
   désormais recevoir des choix connus au rendu (`SettingsSection.choices["<liste>.<champ>"]`).
3. **Les clés.** Une clé `mwk_…` est générée côté serveur, montrée une seule fois (sur la fiche du réveil, action
   « Générer une clé neuve » ; ou `mika wakeup key <nom>`). Seules son empreinte SHA-256, un indice, sa date et son
   auteur sont gardés (`settings`, clé `wakeup_keys`). Une clé neuve rend l'ancienne inutile, « Retirer la clé »
   ferme le réveil, et un réveil retiré emporte sa clé. Le message qui montre la clé n'entre pas dans l'audit des
   actions.
4. **`wakeup.called` fige le réglage** au moment de l'appel : texte et consignes (des contenus que l'oubli atteint),
   mode, projet, lots, réveil, destinataire, échéance. Changer un réveil ne réécrit jamais un appel reçu. L'événement
   est public : le corps et les exécutions de projet le lisent.
5. **Le travail.** Le plugin propose, pour chaque réveil, son plus ancien appel en attente, un à la fois par réveil,
   et un seul par projet. Deux candidats sur la même ligne (le même projet, le même mode) mêleraient leurs gardes :
   l'annulation de l'un ferait tomber l'autre en plein travail. Un seul plan (`prompt.plan`) décide qui part et dit
   pourquoi les autres attendent ; la console lit ce même plan.
   - *Sans projet* : deux sortes d'épisodes neuves, cible `task:wakeup:<seq>`, dans la voie de fond, ni dans le fil
     ni livrées :
     - `WAKE`, dans son mode à elle (rôle « projet », persona compacte, son humeur) ;
     - `WAKE_JOB`, impersonnel (rôle « job », sans persona, sections affectives et intérieures muettes).

     Les deux reçoivent les lots du réveil plus `wakeup`, qui ne contient que `report_wake` : « fait »,
     « impossible » ou « pas_fini », et un compte rendu. L'outil clôt la boucle.
   - *Sur un projet* : une exécution de ce projet, `WORK` ou `JOB` **selon le réveil** (pas selon le projet), avec
     ses outils de base (`projects`, `workshop`) plus ceux du réveil. La preuve vaut 13, au-dessus des exécutions
     ordinaires, pour que ses arguments l'emportent sur la ligne. `report_run` la conclut et le verdict devient
     l'issue de l'appel, retrouvé par corrélation. Elle compte dans les plafonds du projet mais ne touche ni à son
     agenda ni à son espacement : elle n'avale pas un « Lancer maintenant » en attente. Elle attend que rien ne sorte
     de l'atelier (une commande, un envoi git : le fait `projects.outgoing`), comme une exécution ordinaire. Le rendu
     du projet et le mode du compte rendu suivent la sorte d'épisode.
   - *La garde* : l'appel ne doit être ni expiré ni annulé. Jamais « en attente » : son propre compte rendu la
     ferait tomber.
   - *Les fins* :
     - devancé ou cédé : l'appel repart en attente, 30 s plus tard ;
     - panne, délai ou arrêt : un essai de plus (3 par défaut), espacé (2 min, puis 4…), puis l'appel est dit
       échoué ;
     - à court de tours d'outils, ou fini sans compte rendu : « pas fini » — elle a travaillé, rien n'est rejoué ;
     - plus de 12 départs : échoué (jamais une boucle).
   - *L'expiration* : un appel resté en attente au-delà de sa durée de vie n'est plus traité (`wakeup.expire`) ; un
     appel dont le projet a été archivé est clos tout de suite, sans retenir ceux de son réveil qui le suivent. Un
     opérateur peut annuler un appel en attente ou en cours.
6. **Les consignes priment, le texte est cité.** La section « CE QU'ON TE DEMANDE » est de confiance : à quoi sert le
   réveil, ses consignes, à qui ira le compte rendu, comment conclure. Le texte de l'appel va dans « CE QUE L'APPEL
   T'APPORTE », une section citée (une donnée venue d'ailleurs, coupée en dernier recours sous 1 200 caractères). Il
   n'entre jamais dans le brief, qui est le message de confiance ; c'est la forme du brouillon de courrier (ADR 0037).
7. **Le sommeil.** Un réveil qui ne passe pas outre son rythme attend qu'elle soit éveillée. En impersonnel aussi :
   le corps ne retient pas un `JOB`, c'est le proposeur qui attend. Un réveil qui passe outre son rythme :
   - le corps interprète `wakeup.called` et émet `body.roused` (raison `call`, sans adresse) ;
   - elle émerge, le visage s'éveille, et elle se rendort au calme comme après le message d'une proche ;
   - son candidat vaut 17, au-dessus de la barre de réveil : rien de son corps ne le retient ;
   - son compte rendu aussi (17) : il part aussitôt, la nuit comprise — qui a voulu qu'un appel la réveille veut en
     savoir le résultat ; la fiche le dit.

   Un interprète ne tourne pas sur un simple ajout : `Kernel.interpret` est devenu public, et le port l'appelle après
   avoir journalisé l'appel.
8. **Rendre compte.** Ce qu'un appel a donné (fait, impossible, pas fini, échoué — ou qu'il a expiré sans être
   traité) se dit à qui le réveil le dit, par une initiative due :
   - la raison `wakeup_done` est dans `agency.OWED` ;
   - l'initiative part là où la personne est, sinon où on peut lui écrire absente ;
   - tout ce qui attend une même personne part d'une fois ;
   - un compte dont la divulgation n'atteint pas « personnel » n'a pas de candidat.

   La section « CE QUE TES RÉVEILS ONT DONNÉ » (citée, niveau personnel) le montre aussi dans sa réponse si la
   personne écrit ; ce que son prompt lui a montré quand elle a parlé est réputé dit. Elle en montre deux au plus,
   bornés pour tenir sous son plancher : une section coupée en partie compterait pour dite en entier. Elle essaie au plus 3 fois,
   espacées d'une demi-heure, et plus du tout passé 12 h. Avec « personne », le compte rendu reste dans la console.
9. **La console.** Une entrée à elle, « Ses canaux › Réveils par API », montre les réveils et leurs derniers
   appels. La fiche « réveil » a deux onglets : *État* (ce qui a été déclaré, des avertissements, sa clé, comment
   l'appeler) et *Appels* (ce qu'ils apportaient, où ils en sont, pourquoi ils attendent, leur compte rendu,
   l'épisode, « Annuler »). La ligne de commande : `mika wakeup list | key <nom> | revoke <nom>`.

**Conséquences.**

- *Sans réveil déclaré, rien ne change.* Les deux nouvelles sortes d'épisodes sont des sortes de travail (`WORKING`) :
  la mémoire, les flux, la caméra et la Forge les servent comme un pas. Le courrier ne s'ouvre que si le réveil a
  pris son lot (comme pour un projet). Un serveur extérieur sert « quand elle travaille ». Dans son mode, son corps
  (rythme, fatigue) et son humeur la suivent ; en impersonnel, non.
- *Réserves.* Le texte d'un appel vient d'ailleurs, et l'épisode a les droits de sa propriétaire :
  - ne donner à un réveil que les outils qu'il lui faut ;
  - la fiche avertit quand un réveil a sa mémoire et un outil qui fait sortir des données.

  Un outil extérieur qui demande l'accord de l'opérateur répond plus tard, hors du réveil. Sur un projet, le plafond
  horaire des exécutions peut retenir un réveil, et le rythme des exécutions le fait partir en deux minutes environ.
  Un réveil sans projet part en quelques secondes. Les fenêtres « par heure » sont en mémoire : un redémarrage les
  oublie ; la porte vérifie ses plafonds et journalise sous un verrou (deux appels simultanés ne passent pas tous
  les deux sous un plafond d'un seul). Une clé d'idempotence vaut pour toujours pour ce réveil, et un rejeu rend
  l'appel déjà reçu, plafonds atteints ou non. Un arrêt entre l'appel et son interprétation laisse l'appel sans
  réveil du corps ; il part quand même, à 17. Le compte rendu d'un réveil qui a sa mémoire et prévient un compte
  qui n'est pas propriétaire n'est trié que par sa discrétion : la fiche le dit. Sur un projet, son compte rendu
  devient le dernier compte rendu du projet, que les exécutions suivantes lisent (comme pour un projet qui lit du
  courrier).

Épreuves :

- `tests/unit/test_wakeup.py` :
  - un appel part avec les seuls outils du réveil, son texte cité et jamais dans le brief, ses consignes là, sans
    être supplanté par son compte rendu ;
  - impersonnel, ni persona ni humeur ;
  - une panne réessayée, de plus en plus espacée, puis échouée ; à court de tours d'outils : « pas fini », rien
    n'est rejoué ; un appel en attente qui expire (et sera dit) ; l'annulation par un opérateur ;
  - à 3 h, l'ordinaire attend son réveil, celui qui passe outre la réveille puis elle se rendort ;
  - le compte rendu dit une fois à sa propriétaire, et à personne quand le réveil ne prévient personne ;
  - la clé d'idempotence ;
  - sur un projet : une exécution dans le mode du réveil, qui ne touche pas à l'agenda ; deux réveils sur le même
    projet partent l'un après l'autre, et annuler l'un ne fait pas tomber l'autre ; un projet archivé clôt aussitôt
    ses appels.
- `tests/protocol/test_wakeup_web.py` :
  - chaque statut HTTP ; une clé neuve ou retirée ; un rejeu idempotent rendu même au plafond ;
  - un corps hostile (JSON illisible ou très imbriqué, envoi par morceaux trop gros) refusé proprement ;
  - la clé gardée nulle part (ni dans les réglages, ni dans l'audit, ni sur la fiche) ;
  - la page d'un réveil (projets et destinataires proposés, un projet ou un lot inconnu refusé, le nom fixe).

Une relecture indépendante a trouvé, avant qu'ils ne partent : deux candidats sur le même projet qui mêlaient leurs
gardes, des essais sans espacement, une fin à court de tours rejouée comme une panne, un appel d'un projet archivé qui
retenait son réveil un jour, un réveil sur projet qui partait pendant un envoi git, une section de comptes rendus
qui pouvait compter pour dit ce qu'elle avait coupé, une ligne « un réveil par API t'a tirée du sommeil » dite à tort
après une parole qui l'avait réveillée, un rejeu idempotent refusé au plafond, l'annulation offerte hors de la fiche.

Trois mutations les font échouer :

- le texte de l'appel non cité ;
- une garde « en cours » au lieu de « ni expiré ni annulé » ;
- une porte qui ne compare plus la clé.
