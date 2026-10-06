# 0069 — Teams : lire et écrire par l'extension du navigateur

**Contexte.** La propriétaire a demandé (2026-10-06) que Mika lise ses conversations Teams et y réponde, **sans les
API de Microsoft** : déclarer une application dans Azure (Graph, Bot Framework) demande le consentement d'un
administrateur que son organisation ne donnera pas. Une extension de navigateur (`frontend/Extension`, « Mika ·
Teams ») lit déjà ce que le client web de Teams reçoit, dans l'onglet de la personne : les réponses du service de
chat, les trames du WebSocket et la base IndexedDB du client. Elle l'envoyait d'abord comme signaux d'appareil
(`POST /api/perceptions`, ADR 0068 pour la forme de la porte) : 400 caractères, aucune conversation, aucun message
désigné. L'attention les remarquait, mais Mika ne pouvait ni relire un fil ni y répondre. La propriétaire a tranché
trois questions :

- ce qui part est, par défaut, un **brouillon posé dans Teams** (la personne l'envoie), et le mode est réglable :
  *après accord*, ou *autonome* ;
- elle prépare d'elle-même une réponse **quand un message reçu pose une question sur laquelle elle peut aider** (et
  à la demande) ;
- une **signature** (« — rédigé avec Mika ») est un choix.

**Décision.**

1. **Un plugin `teams`, calqué sur le courrier (ADR 0027, 0037, 0044).** Le monde vit hors du journal : l'adaptateur
   `adapters/teams/store.py` (`teams.db`) garde les conversations, les messages, les brouillons et la file. Le
   journal garde ce qu'elle remarque (`teams.noticed`, un `Signal`), ce qu'elle propose (`effect.proposed`, capacité
   `teams.send`) et ce qui est arrivé à ses réponses (`teams.settled`, `teams.sent`). Une référence de message
   (`t…`) est attribuée par l'adaptateur, jamais par l'extension.
2. **Une porte à clé, calquée sur les réveils (ADR 0068).** Trois routes :
   - `POST /api/teams/inbox` : un lot de messages et de conversations ;
   - `GET /api/teams/outbox` : ce qui doit repartir ;
   - `POST /api/teams/outbox/<id>` : un accusé (`sending`, `placed`, `sent`, `failed`). `sending` **réserve** un
     envoi avant de le faire : un seul navigateur l'enverra, le second (ou un second essai) reçoit 409, et l'élément
     n'est plus offert. Une issue incertaine (l'envoi a commencé, sans réponse nette) n'est ni accusée ni retentée :
     un message de la personne qui lui ressemble la règle, sinon l'échéance la dit « incertaine ». Un `sent` tardif,
     après l'échéance, est accepté : il dit la vérité.

   La clé `mtk_…` est générée côté serveur et montrée une seule fois (Configuration › Sens › Teams, ou
   `mika teams key`) ; seule son empreinte est gardée. La porte, `app/teams.TeamsDesk`, vérifie avant de rien ranger
   ni journaliser :
   - la clé, en temps constant : absente ou fausse, le même 401 ;
   - que Teams est actif ;
   - la forme du lot : un message ou une conversation illisible (identifiant, date invraisemblable, texte vide) est
     **écarté seul** (`dropped`), un demi-caractère (une coupe au milieu d'un emoji) est réparé ; seule une
     enveloppe illisible fait refuser le lot ;
   - une cadence par minute.

   Sans clé bien formée, le corps n'est même pas lu. Un message supprimé dans Teams (`deleted`) efface son texte
   du cache ; un message retouché y remplace le sien.

   L'origine acceptée est une extension (`chrome-extension://`, `moz-extension://`), aucune, ou celles du site (sa
   console, son frontend : elles n'ont pas la clé). L'extension n'entre pas dans les origines du site, ce qui lui
   aurait ouvert `/ws`. Le corps est borné, même envoyé par morceaux, et
   toute réponse porte `no-store`.
3. **Remarquer.** Le processus `teams.triage` (réveillé par `teams.received`, qui ne porte que des comptes et des
   identifiants de conversation) lit les messages reçus, jamais ceux de la personne. Il les trie avec le rôle
   `triage` : importance, question à la personne, et *peut-elle aider sans savoir ce qu'elle ne peut pas savoir*. Un
   message n'est pour elle que s'il est adressé à la personne : tête-à-tête, groupe, ou mention. Une conversation
   exclue se décide ici (le nom d'un groupe, choisi par d'autres, ne va pas au journal). Un arriéré plus grand qu'un
   passage est lu jusqu'au bout ; un passage qui échoue est repris. « La personne a déjà répondu » se juge à l'heure
   Teams de son message, jamais à l'heure où il arrive (un vieux message rattrapé ne répond pas à une question
   posée après).
4. **Préparer** (`Kind.TASK`, cible `task:teams:<réf>`, raison `teams_draft`).
   - **Le message visé.** Par conversation, le dernier message qui appelle une réponse. Il doit être récent (2 h par
     défaut), sans réponse de la personne depuis, dans une conversation non exclue, et aucune autre réponse ne doit
     déjà être en chemin.
   - **Le budget.** Au plus 8 réponses par jour et 2 essais par message. Une réponse déjà proposée à un message
     (refusée, partie, laissée) n'est jamais reproposée d'elle-même : seule une demande la relance. Dans la tâche,
     `teams_draft` ne répond qu'au message confié (un message cité ne l'envoie pas ailleurs). Teams désactivé, rien
     n'est préparé ni proposé.
   - **Les outils.** Le lot `teams` seul. Sa mémoire n'est pas de la partie : les outils de mémoire ne servent pas
     les tâches, et une réponse part chez des collègues.
   - **Le prompt.**
     - Le fil est cité (« LE MESSAGE TEAMS AUQUEL TU PRÉPARES UNE RÉPONSE »).
     - Sa voix est de confiance (« COMMENT TU ÉCRIS DANS TEAMS ») : elle écrit **à la place** de la personne, à la
       première personne, sans évoquer sa nature ni rien de privé de qui que ce soit, en laissant
       `[À COMPLÉTER : …]` ce qu'elle ne sait pas.
     - Puis le ton et les consignes, réglés par un opérateur.
   - **À la demande.** Une demande d'opérateur (`teams.draft_asked`, sur la fiche d'une conversation) passe devant,
     hors plafond.
5. **Partir.** L'outil `teams_draft` range le brouillon dans l'adaptateur et propose `teams.send` avec l'aperçu et
   son condensé ; le journal n'a jamais le texte. La capacité (idempotente) **met en file** : elle ne fait rien
   partir elle-même. Selon le mode :
   - **brouillon** (par défaut), sans accord : l'extension le pose dans la zone de saisie de la conversation, et
     c'est le geste de la personne qui vaut accord. Un `[À COMPLÉTER]` peut y être posé : la personne le remplira ;
   - **validation** : une carte d'accord va à la personne dans le chat (`_decider`, ADR 0064) et à la console
     (Approbations, ou la fiche de la réponse : envoyer, retoucher, refuser, reprendre). La carte va à une adresse
     de propriétaire présente (n'importe laquelle), sinon joignable absente. Sans accord dans le délai (2 h par
     défaut), `teams.expire` refuse au nom du délai : elle le sait comme « pas d'accord à temps », pas comme un
     refus ;
   - **autonome** : sans accord.

   En validation comme en autonome, un `[À COMPLÉTER]` ne part jamais. L'extension envoie par le service de chat
   (avec l'en-tête que le client Teams utilise lui-même, gardé dans la page), ou par la zone de saisie si la
   conversation est ouverte. Ce qui part est ce que l'aperçu montrait : le texte final, signature comprise, est figé à
   la mise en file.
6. **Savoir ce qu'il est devenu.** Un message de la personne dans la conversation, après que la réponse a été posée,
   la règle :
   - s'il lui ressemble (ressemblance ≥ 0,5), elle est **partie**, *retouchée* si le texte diffère ;
   - sinon, elle **n'a pas servi** : la personne a écrit autre chose.

   L'accusé de l'extension dit le reste (posée, partie, échec). Une réponse que personne n'a posée ni envoyée en 8 h
   ne part plus. Partie, elle le sait (`teams.sent`, un signal) ; « TES RÉPONSES TEAMS » lui montre ce qu'elles sont
   devenues, refus et notes compris, pour qu'elle en apprenne.
7. **La signature** (réglage, décochée par défaut) est ajoutée par l'adaptateur, jamais écrite par le modèle : la
   voix « à ta place » lui interdit de parler d'elle. Cochée, ses collègues savent qu'une IA a écrit. Son texte par
   défaut, « — rédigé avec {elle} », prend son nom dans sa persona (ADR 0070 : le code ne l'écrit jamais).
8. **Les collègues** ne sont pas ses interlocuteurs.
   - Pas d'adresse `ext_…`, qui ouvrirait relances, attentes et initiatives.
   - Une clé de sujet `teams:<identifiant>` dans `about`.
   - L'oubli l'atteint dans le journal *et* dans le cache (hook `forget` : ses messages, ses tête-à-tête entiers, et
     les réponses à ses messages ailleurs). Le courrier, lui, n'a pas ce hook. Au journal, la raison d'un échec est
     écrite par le code ; le détail que donne l'extension reste dans le cache.
9. **La console.** « Ses canaux › Teams » : conversations (fiche : le fil, « Lui demander une réponse »), réponses
   (badge : à décider ; fiche : exactement ce qui part, et les décisions) et l'extension. Les réglages (Configuration
   › Sens › Teams) portent :
   - actif ;
   - le mode ;
   - le nom, le ton et les consignes ;
   - la signature ;
   - l'initiative et les conversations exclues ;
   - la clé (nouvelle, retirée).

   Le mode, l'initiative et les exclusions passent aux paramètres par `Live.inputs()`, comme les boîtes du courrier.

**Conséquences.**

- *Rien ne parle à Microsoft depuis le serveur.* Tout dépend de l'extension, qui dépend du client Teams :
  - celui-ci peut changer sans prévenir ;
  - l'extension reconnaît un message à sa forme plutôt qu'à une adresse ;
  - son diagnostic dit quelle source capte et si la zone de saisie et l'envoi sont possibles.

  La zone de saisie et la forme de l'envoi restent à caler sur le vrai Teams de la propriétaire.
- *Réserves.*
  - Elle écrit sous le nom de quelqu'un, à des collègues. Le mode par défaut ne fait rien partir sans le geste de la
    personne, et le mode autonome se choisit explicitement.
  - Le texte des messages entre dans le journal (résumés), dans `teams.db` et dans ses prompts : il part donc chez le
    fournisseur du modèle. Pour un Teams de travail, c'est à la charte de l'employeur de dire si c'est permis.
  - Une conversation exclue dans l'extension ne quitte jamais le navigateur.
- *Ce que la v1 de l'extension envoyait en signaux* (`/api/perceptions`) ne passe plus par là ; le plugin `sensors` ne
  change pas.
- *Pas fait.*
  - Annoncer d'elle-même un message important à la personne (le courrier le fait, ADR 0044).
  - Une recherche dans les messages.
  - Un scénario du simulateur (le courrier n'en a pas non plus pour ses brouillons).

Épreuves :

- `tests/unit/test_teams.py` :
  - une question où elle peut aider devient une réponse posée, à la place de la personne : le message cité, ni
    mémoire ni identité dans ses outils, aucun texte au journal ;
  - posée puis envoyée retouchée, elle le sait ; la personne écrit autre chose : pas servie ;
  - en validation, la carte va à la personne et rien n'est en file avant l'accord ; sans accord à temps, refusée au
    nom du délai ;
  - autonome, sans accord ; un blanc ne part jamais seul mais se pose pour la personne ;
  - ni un canal sans mention, ni une conversation où la personne a répondu, ni un message trop vieux, ni une
    conversation exclue ; sans initiative, seulement à la demande ;
  - la signature ajoutée par le serveur ;
  - personne ne l'envoie : elle ne part plus ;
  - oublier un collègue atteint le journal et le cache.
- `tests/protocol/test_teams_web.py` :
  - la clé (401 identiques, une clé neuve, retirée, jamais gardée en clair) ;
  - les origines ;
  - un lot illisible, trop grand ou daté de l'avenir refusé avant tout rangement ; Teams désactivé ;
  - la file, et des accusés rejoués sans effet, impossibles (409) ou inconnus (404).

Une relecture indépendante (serveur et extension) a trouvé, avant qu'ils ne partent : « elle a déjà répondu » jugé
à l'heure d'arrivée ; une réponse refusée reproposée ; un arriéré jamais lu ; un passage de tri raté jamais repris ;
une tâche qui pouvait répondre ailleurs ; Teams désactivé qui proposait encore ; une carte adressée à une
propriétaire absente ; un refus au nom du délai présenté comme celui de la personne ; le nom d'un groupe au journal ;
un emoji coupé qui faisait refuser un lot entier ; un même envoi possible depuis deux navigateurs ; un accusé tardif
refusé. Chacun a son épreuve, et chaque correction l'a vue échouer quand on la défait.

Cinq mutations les font échouer :

- la signature non ajoutée ;
- une validation sans accord ;
- un blanc accepté en mode autonome ;
- un canal traité comme adressé ;
- un message de la personne toujours pris pour le brouillon.
