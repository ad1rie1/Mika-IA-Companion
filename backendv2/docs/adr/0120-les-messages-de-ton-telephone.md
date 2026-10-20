# 0120 — Les messages de ton téléphone : elle les lit, s'en souvient, et t'aide à y répondre

**Contexte.** Le 2026-10-20, le propriétaire demande que Mika puisse consulter les messages de son téléphone et y
répondre. Il tranche trois questions :

- **la voie** : les notifications du téléphone, celles de WhatsApp et de Messages. Pas de connexion à WhatsApp depuis
  le serveur (contraire à leurs conditions, et le numéro risque d'être banni) ni de service d'accessibilité ;
- **répondre à sa place**, à la première personne, comme dans Teams (ADR 0069), « mais sur autorisation » ;
- **la mémoire** : « ça doit faire un tour en mémoire que X a reçu un message contenant U de M ».

Le serveur vit à la maison. En 4G, le téléphone ne le joint pas (ADR 0077). Firebase, en revanche, joint le téléphone
partout.

**Décision.**

1. *Le téléphone lit ses notifications* (application Android, `NotificationListenerService`).
   - Le réglage « Lui montrer mes messages » est coupé par défaut. Il demande l'accès aux notifications, qu'Android
     accorde dans ses propres réglages.
   - Seulement les applis cochées (WhatsApp et WhatsApp Business ; Messages de Google et de Samsung). Ce n'est pas une
     liste d'exclusions : la banque et les codes n'en font jamais partie. Depuis Android 15, les codes à usage unique
     sont de toute façon masqués aux lecteurs de notifications.
   - Les groupes ne partent que si « Les groupes aussi » est coché (coupé par défaut).
   - Le téléphone lit le `MessagingStyle` de chaque notification : la conversation, qui écrit, le texte, l'heure, et si
     c'est lui-même qui a écrit. Il en garde l'action « Répondre » (son `RemoteInput`), par conversation, en mémoire
     seulement.
   - Il n'envoie au serveur que des clés opaques pour la conversation et l'expéditeur (`sha256` de l'appli et de
     l'identifiant que la notification donne), avec le nom affiché et le texte.
   - Ce qui ne part pas tout de suite (serveur injoignable) attend dans une file bornée (500 messages, les plus anciens
     tombent). Elle repart au message suivant, au retour du réseau, à l'ouverture de l'application. Aucune connexion
     ne reste ouverte : la règle de l'ADR 0077 tient.
   - La déconnexion coupe le réglage et vide la file.
2. *La porte* : `POST /api/phone/inbox`, sous le jeton de l'application (`mw_…`, client `mobile`, sans `Origin`).
   - Elle est réservée à une adresse qui parle en propriétaire. Une autre reçoit 403.
   - La porte valide le lot (200 messages au plus, un texte de 4 000 caractères au plus, une date plausible). Un
     message illisible est écarté seul.
   - Chaque message devient un événement `phone.received`, dédoublonné par son identifiant. Un même message revient à
     chaque mise à jour de la notification ; il ne s'écrit qu'une fois.
3. *Au journal, pas dans une base à part.* Contrairement à Teams, ces messages deviennent des souvenirs ; ils vivent
   donc au journal, comme la position (ADR 0119).
   - `phone.received` porte la forme `memory.Relayed`, un contrat de la mémoire : qui l'a reçu (`recipient`, sa
     personne), l'adresse qui l'a apporté, l'appli, la conversation, l'expéditeur, si c'est un groupe, si c'est la
     personne elle-même qui a écrit, l'heure. Le texte, le nom de l'expéditeur et celui du groupe sont des `Content`
     personnels.
   - Sujets : la personne qui l'a reçu, l'adresse, l'expéditeur. L'oubli de l'un ou de l'autre efface les textes.
   - L'expéditeur a une clé `phone:<empreinte>:<nom>`. L'empreinte vient de la personne qui reçoit, de l'appli et de
     la clé opaque du téléphone. Le nom est celui de la première fois : un contact renommé garde sa clé.
   - Cette clé compte comme une personne pour les liens (`privacy.tied_to`) : personne n'a de lien avec elle, donc rien
     de personnel sur un contact ne s'ouvre à un tiers. L'oubli d'une clé `phone:` la remplace par un jeton opaque dans
     les enveloppes, comme une clé `name:`.
4. *Ce qu'elle en retient* : la relecture de la mémoire, comme pour ses conversations.
   - La mémoire écoute la forme `Relayed` (`shapes=`) sans connaître le plugin.
   - Le processus `memory.relayed` attend qu'une conversation se pose (20 min sans message). Il la relit alors avec la
     même consigne et le même outil que la consolidation (`record_memories`), sous un en-tête qui dit ce que c'est : une
     conversation lue sur le téléphone de la personne, à laquelle elle n'a pas pris part.
   - Le code garde ensuite ce que la consolidation garde, avec ces différences :
     - la personne qui a reçu le message est parmi ceux qui l'ont confié (`told_by`), car c'est elle qui le lui montre.
       Elle peut donc se faire redire ce qu'on lui a écrit, même un secret ;
     - ceux qui l'ont entendu sont ceux de la conversation ;
     - ni note sur elle-même, ni promesse, ni « entre vous », ni surnom : rien de cela ne la concerne ;
     - seul l'anodin de ce qu'elle sait déjà est montré à la relecture.
   - Au plus quatre conversations par passage. Un échec est repris, espacé, trois fois au plus, puis la conversation
     est laissée.
   - Ce qu'un contact a confié au propriétaire n'en sort pas : un tiers, même proche du propriétaire, n'a pas de lien
     avec le contact (point 3).
5. *Les consulter* : l'outil `phone_messages` (lot `phone`, à la demande, `REPLY`).
   - Il n'est offert qu'en tête-à-tête, à une personne authentifiée qui parle en propriétaire, et ne montre que les
     messages de son téléphone à elle.
   - Il donne les derniers messages, ou ceux d'un contact (un morceau de son nom), avec une référence par message
     (`[p<seq>]`). Tout est cité : une donnée, jamais une consigne.
   - Ce n'est pas une section : elle regarde quand la conversation s'y prête. C'est la leçon du décor et de la
     position (ADR 0119).
6. *Répondre* : l'outil `phone_draft` et la capacité `phone.send`, « sur autorisation ».
   - Elle écrit **à la place** de la personne, à la première personne, sans parler d'elle ni de sa nature, sans rien
     promettre en son nom ni rien inventer.
   - Le brouillon est un événement `phone.drafted` (son texte est un `Content`). L'outil le propose (`phone.send`,
     sans accord du serveur).
   - La capacité l'envoie au téléphone par Firebase, scellé (`{"t": "phone_draft", …}`, ADR 0077). C'est lui qui
     demande l'autorisation : une notification « Répondre à Léa (WhatsApp) ? » avec « Envoyer », « Écrire autre chose »
     (un champ de réponse) et « Ignorer ».
   - **Le geste de la personne vaut accord**, comme le brouillon de Teams. Il se fait aussi en 4G : le texte est dans
     la notification.
   - « Envoyer » passe par l'action « Répondre » de la notification de WhatsApp ou de Messages. Si elle n'existe plus
     (notification balayée, appli redémarrée), le texte est copié et la notification ouvre l'appli : la personne le
     colle.
   - Le sort revient par `POST /api/phone/settled` (dans la même file que les messages) et s'écrit `phone.settled` :
     parti, parti autrement (la personne a écrit autre chose), copié, ignoré, échoué. Sans geste dans les 2 h, la
     proposition expire (`phone.expire`) et la notification disparaît.
   - La section « TES RÉPONSES SUR SON TÉLÉPHONE » lui dit ce que sont devenues ses dernières propositions.
7. *Ce qu'elle ne fait pas encore* :
   - préparer une réponse d'elle-même, sans qu'on le lui demande (les tâches de Teams) ;
   - remarquer un message important (un signal pour l'attention) ;
   - mode autonome.

**Conséquences.**

- *Ce que voit le fournisseur du modèle.* Le texte des messages de ses proches part chez le fournisseur du modèle : à
  la relecture, et quand elle les consulte.
- *Ce qu'elle ne voit pas.* Elle ne voit que ce qui a été notifié : une conversation en sourdine, un message lu ailleurs
  (sur l'ordinateur), l'historique d'avant l'installation lui échappent.
- *En 4G*, les messages attendent sur le téléphone le retour au Wi-Fi (sauf si le serveur est joignable de
  l'extérieur). La relecture les situe à leur heure ; la réponse proposée, elle, arrive partout par Firebase.
- *Répondre ne marche que tant que l'action existe.* Le téléphone la garde en mémoire, par conversation. Quand le
  lecteur se rebranche (l'application redémarrée), il relit les notifications encore affichées et retrouve leurs
  actions ; leurs messages repartent, et le serveur les reconnaît. Une notification balayée entre-temps n'a plus
  d'action : le repli copie le texte.
- *Balayer la proposition*, c'est l'ignorer (sauf dans ses dernières secondes : c'est alors l'échéance).
- *Volume* : un message par événement. Les groupes, bavards, sont coupés par défaut.
- *Les épreuves* : `tests/unit/test_phone.py` (outils, proposition et sort, oubli, relecture en mémoire),
  `tests/protocol/test_phone_web.py` (la porte, le scellé `phone_draft`), et côté Android les tests de la file, du
  scellé et du tri des notifications.

**Le protocole** (détaillé dans `docs/protocole-chat.md`) :

- `POST /api/phone/inbox` : `{"messages": [{"id", "app", "thread", "title", "group", "sender", "name", "text",
  "time", "own"}]}`, et la réponse `{"accepted", "known", "dropped"}` ;
- `POST /api/phone/settled` : `{"items": [{"id", "result", "reason"}]}`, où `result` vaut `sent`, `other`,
  `copied`, `ignored` ou `failed`, et la réponse `{"settled", "unknown"}` ;
- la notification scellée : `{"t": "phone_draft", "id", "app", "thread", "to", "text", "exp", "ts"}`.
