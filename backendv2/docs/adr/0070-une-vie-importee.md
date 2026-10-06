# 0070 — Une vie importée : sa nature, son nom, la genèse et l'avance rapide

**Contexte.** Un « jumeau numérique » se prépare (dossier `INJECTION/` à la racine du dépôt) : une personne réelle,
reconstruite à partir de ses archives — mails, notes, journaux, messageries — puis **vécue en accéléré** dans le
noyau, sur une horloge virtuelle partant de son premier message. L'utilisatrice veut une **incarnation totale** : le
personnage ne s'appelle pas Mika, a une vie humaine et ne se dit jamais une IA. Or le moteur supposait Mika l'IA
VTuber à plusieurs endroits : la consigne de sa nature (`self.NATURE` : « Tu es une IA, une VTuber »), la ligne qui
présente sa propriétaire (« ton serveur, tes réglages »), le nom écrit en dur dans les consignes des modèles de fond
(« Tu es la mémoire de Mika », la fiche d'une personne, le résumé d'un fil long, le tri du courrier, la description
d'une image), l'étiquette de ses répliques montrées à la relecture (« Mika : … »), l'expéditrice de ses mails, la
signature de ses enregistrements d'atelier, les libellés de la console. Il n'avait enfin **aucun chemin d'import** :
une mémoire n'y naît que de ses processus, en relisant ses conversations.

**Décision.**

1. *Sa nature est un champ de sa persona.* `PersonaDoc.nature` vaut `ia` (une IA qui le sait — la persona livrée, la
   valeur par défaut) ou `incarnee` (une personne). Le rendu de la persona choisit sa consigne de nature
   (`self.nature_of`) : incarnée, « Tu es toi, avec ton histoire, tes proches et tes souvenirs » — ni IA, ni
   personnage, ni rôle, et pas « une humaine qui s'ignore ». La ligne qui présente sa propriétaire suit
   (`identity.owner_line`) : quelqu'un qui veille sur elle, plus « ton serveur ». Les libellés de sa vie (`life`,
   `facts`, la page « Sa vie ») cessent de dire « IA VTuber ». Un journal plus ancien se relit sans upcaster : le
   champ a un défaut, une persona d'avant reste une IA qui le sait, au rendu identique.
2. *Son nom vient de sa persona, partout.* `self_.name_of(persona)` le donne (le défaut, `DEFAULT_NAME`, est le seul
   « Mika » du code) : les consignes de la relecture, de la fiche, du résumé, du tri et des descriptions d'images
   sont des gabarits (`system(nom)`), ses répliques sont étiquetées de son nom, la mémoire la reconnaît sous son nom
   et son prénom (`extraction.self_names`), un « Nom : » recopié en tête de réponse se retire d'après son nom
   (`PersonaRender.name`, transmis à l'analyse de la réponse). Un adaptateur ne lit pas sa persona : l'application
   lui passe son nom (`ImapSmtpMail(her=…)`, `BwrapWorkshop(author=…)`). La console dit « elle », « elle-même » (le
   mode de travail d'un projet), « sa » là où elle disait « Mika ». Un test d'architecture
   (`tests/architecture/test_her_name_comes_from_her_persona.py`) refuse toute chaîne du code qui écrit « Mika »,
   hors docstrings, hors simulateur, sauf une liste blanche justifiée : le défaut de la persona, et deux
   `User-Agent` qui nomment le logiciel auprès de serveurs distants.
3. *La couture d'import : `app/genesis.py`.* Sur un noyau démarré, `remember`, `believe` et `note_event` ajoutent à
   l'instant courant un souvenir, une croyance (sur quelqu'un, le monde, ou elle-même : `about_self`, `durable`) ou
   un moment de la vie de quelqu'un : `memory.remembered`, `memory.believed`, `memory.event_noted`, émis au nom de
   `memory`, avec **`origin=GENESIS`**. C'est une exception, assumée, à « ce qu'elle garde est écrit par sa voix ou
   dérivé des faits » : ce sont des souvenirs venus de **ses propres archives**, datés par l'horloge du rejeu (le
   journal n'accepte pas d'antidate : on rejoue dans l'ordre). Tout passe par `Mind.append` — dédoublonnage par la
   clé que donne l'appelant, validation, réducteurs, projections (`memory_items`), index des vecteurs, rappel — et
   donc par l'oubli : chaque texte déclare qui il concerne et qui l'a confié, en **clés canoniques** vérifiées
   (`genesis.person_key` : un compte `user_…`, un compte extérieur `ext_…`, une adresse déjà vue, ou `name:…` replié
   comme la mémoire le forme — `genesis.named`). Une clé mal formée (un prénom nu, `anon_…`, sa tuyauterie) est
   refusée avant tout ajout : `forget` ne l'atteindrait jamais. Le `call_id` d'un élément importé vaut `archive`.
4. *Le préréglage « avance rapide ».* Pendant un rejeu, l'archive dit déjà ce qu'elle a fait : sa vie spontanée ne
   doit pas s'y ajouter. `genesis.begin_fast_forward` pose, à l'étage « surcharge » de `runtime/params.py`, un jeu
   nommé (`genesis.FAST_FORWARD`) journalisé comme toute configuration (`kernel.params_changed`, relu tel quel au
   rejeu) ; `end_fast_forward` le lève et rejournalise la configuration d'avant. Il coupe : le budget d'initiatives
   ordinaires (`agency.daily_cap` = 0 : prendre la parole, prévenir, relancer, raconter), ce qu'elle entreprend
   d'elle-même (`goals.live_self_max`, `musings_per_day`, `steps_per_hour` = 0 : ni réflexion, ni rêverie, ni
   séance), les projets qu'elle ouvrirait d'elle-même (`projects.live_self_max` = 0), ses murmures (`expression.murmur_chance`, `murmur_charged_chance` = 0), les prises de nouvelles, suivis,
   vœux et encouragements (`others.*_evidence` = 0), les relances d'un manque, la reprise de contact et la recherche
   de réconfort (`social.recontact_evidence`, `rekindle_evidence`, `comfort_evidence` = 0), et tenir une promesse au
   moment dit (`memory.keep_evidence` = 0 — c'est dû, le plafond du jour ne l'arrête pas). Une surcharge du jeu que
   le plan refuserait (un paramètre renommé) fait échouer la pose, plutôt que de laisser sa vie tourner en silence.

**Conséquences.** Aucun événement ne change de forme. `PersonaDoc` gagne `nature` ; `contracts/self_` gagne
`DEFAULT_NAME`, `AI`, `EMBODIED`, `name_of` ; `PersonaRender` gagne `name` ; un `Parser` du pipeline reçoit
`(texte, son nom)` ; `vocab.affect.parse_tag` et `expression.parse` prennent le nom de l'orateur (un « Mika : » ne
se retire plus sans lui). `extraction.SYSTEM`, `social.profile.SYSTEM`, `transcript.COMPACT_SYSTEM`,
`email.poll.TRIAGE` et les `LOOK` de la caméra et des dessins deviennent des fonctions du nom ;
`extraction.tool(nom)`, `profile.tool(nom)`, `People.of(…, her=nom)`. Le mode de travail « Mika » d'un projet
s'appelle « elle-même » dans la console (la valeur journalisée, `persona`, ne bouge pas). Pour la persona livrée,
tout ce qu'elle lit est inchangé, au caractère près, sauf les descriptions des champs de l'outil `record_memories`
(« elle » au lieu de « Mika »). Tests : `tests/unit/test_genesis.py` (gardé, rappelé, oublié avec la personne ;
clés refusées sans rien écrire ; le préréglage journalisé, l'arbitre qui ne lance plus d'initiative ordinaire de la
journée, la levée qui rend les valeurs naturelles), `tests/unit/test_persona.py` (une persona incarnée nommée
autrement : une journée entière — réponses, initiative, relecture, journal, rêve — sans « Mika » ni « IA » dans ce
qu'un modèle reçoit).

**Reste.** Les listes de mots du vocabulaire (`vocab.words.CHATTER`, `SALUTATIONS`) tiennent « mika » pour un mot
de conversation : son nom à elle, s'il est autre, y compte comme un mot qui porte un sujet (un indice de rappel de
plus, rien de faux). Le relais MCP de la CLI Claude Code s'appelle `mika` (ses outils y sont `mcp__mika__…`) : un
nom technique que le modèle voit dans les noms d'outils. La console ne dit pas encore la provenance « archive »
d'un élément (`memory_items` ne garde pas l'origine de l'événement). Les clients web, Unity et Android, qui
l'appellent encore Mika, suivront dans un lot à part. Les ADR précédentes restent telles qu'elles ont été écrites.

**Après la relecture (même jour).**
- **Préréglage.** Il coupe aussi les rappels promis (`goals.remind_evidence` = 0 : ils sont dus, comme une promesse
  tenue). Avec `body.woken_by=()`, une amie qui écrit la nuit ne la réveille plus : l'archive dit si elle a
  répondu, et le pilote libère alors la réponse à son heure. Deux exceptions restent, faute de paramètre :
  - un message urgent la réveille toujours (une constante de `body`) ;
  - la salutation à l'arrivée de quelqu'un, qu'un rejeu de comptes extérieurs sans présence ne déclenche pas.
- **Levée.** `begin_fast_forward` et `end_fast_forward` exigent `overrides`, la configuration en cours (`None`
  pour une vie neuve). Omise, la levée effaçait en silence les surcharges de l'opératrice. La couture sert un
  pilote **hors ligne** : sur un serveur, `Live.reconfigure` rejournaliserait la configuration sans le préréglage.
- **Ce qu'on importe suit les règles de la consolidation.**
  - Un secret est une confidence, même sans personne. `salience.admissible` ne laisse sortir un secret devant
    personne : jusque-là, un secret de ses propres notes, sans personne, sortait dans un salon public.
  - « Entre vous » exige une personne, se tient de première main (`told_by` ⊆ `about`), est au moins personnel
    et compte (importance ≥ 0,7).
  - Une personne en jeu met la sensibilité au moins à « anodin ».
  - La `source` d'une croyance sans confident devient son confident : l'oublier efface le texte.
  - Une croyance sur elle refuse `source` et `heard_by`.
  - Son propre nom, son prénom, « moi » et « elle » ne sont pas des personnes.
  - `user_007` n'est pas l'alias de `user_7` : il est refusé.
- **Son prénom.** Son prénom seul la désigne à l'extraction seulement si personne de la conversation ni de
  l'annuaire ne le porte : une amie qui s'appelle comme elle reste son amie. Le rappel ignore aussi son prénom
  quand quelqu'un le prononce.
- **Une persona incarnée a un nom** : vide, elle s'entendrait appeler « Mika ».
- **`Kernel.release_held()`** relâche les réponses retenues dont le `reply_wait` ne rend plus 0. C'est un pilote
  qui vient de changer ce que son `reply_wait` répond qui l'appelle. Il n'a pas d'effet tant que le noyau ne vit
  pas.
- **Restes acceptés.**
  - Une croyance d'archive qui redit ce qu'une consolidation vient d'extraire n'est dédoublonnée que par la clé de
    l'appelant. Le pilote d'INJECTION ne passe par la genèse que pour ce qui n'est pas rejoué, donc ce cas ne se
    présente pas.
  - Les épisodes impersonnels (JOB) ne retirent plus un « Mika : » en tête de leur texte, qui n'est ni montré ni
    livré.
