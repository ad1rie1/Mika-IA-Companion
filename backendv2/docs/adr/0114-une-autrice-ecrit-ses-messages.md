# 0114 — Une autrice écrit ses messages

**Contexte.** Le banc de conversation (ADR 0112) plafonnait. Avec Sonnet, sa voix en service, il donnait 58 sur 100 ; Opus
partout, ou une seconde passe sur Opus, donnait 64 ou 65. Réécrire une consigne déplaçait le défaut sans le retirer :
moins de questions, mais des réponses jugées « plates ». Rejouées une à une, de vraies répliques ratées montraient
que son portrait seul valait le prompt entier. Le 2026-10-16, la propriétaire montre une conversation tenue avec
Opus sur claude.ai :

- joué tour par tour, le personnage parle comme ici (de longues phrases, des questions, de l'attention à l'autre) ;
- quand on lui demande d'écrire un fil de SMS entier, des deux côtés, le même modèle écrit une conversation qu'elle
  juge parfaite : réactions, messages, sujets, une dispute.

Tour par tour, le modèle reste une assistante qui joue un rôle et s'occupe de son interlocuteur. En autrice, il fait
parler deux personnes, et aucune des deux ne joue au service.

**Décision.**

1. *La seconde passe est une autrice* (rôle `polish`, `expression.polish`). Elle reçoit :
   - sa persona telle que la conversation la rend (son portrait, sa voix, ce qui est vrai d'elle, son caractère) ;
   - qui est l'autre, tel que son état le dit déjà, filtré pour cette audience (« QUI TU AS EN FACE », « LE TON ENTRE
     VOUS », « CE QUE TU SAIS DE CETTE PERSONNE ») ;
   - les 16 derniers messages du fil, une ligne par bulle (« Mika : … », « L'autre : … »), et en dernière ligne le
     premier jet, marqué brouillon (« Mika (brouillon) : … ») : à garder pour ce qu'il veut dire, pas pour ses mots.
2. *Elle écrit quatre échanges d'avance.* Elle réécrit le brouillon, puis écrit la suite : Mika, puis l'autre, quatre
   fois, en se mettant à la place de l'autre. Seuls les messages de Mika qui ouvrent cette suite partent, une bulle
   chacun (`authored`). Au tour suivant, elle repart du vrai fil. Écrire une scène qui continue, et non une réplique
   isolée, lui ôte l'envie de placer une chute à chaque message.
3. *Sa façon de réagir.* Elle ne cherche pas une phrase drôle à chaque message. Elle réagit brut, ou d'une vraie
   phrase, ou d'une vanne, et participe à la conversation sans en être le public. Comme quelqu'un qui texte, elle
   met parfois un émoji.
4. *Le premier jet reste la tête.* Son prompt, son état, sa mémoire et ses outils ne changent pas. Ses balises restent
   celles du premier jet, et l'autrice n'invente rien de ce qu'elle sait ou a fait.
5. *Ses émojis s'écrivent, ils ne se disent pas.* Le texte livré les garde (`parse_tag` ne les retire plus), et la
   voix du client web les saute (`withoutEmoji`) ; un message fait d'un seul émoji reste muet.
6. *Un fil de référence, facultatif* (`PersonaDoc.reference_thread`, console › Sa parole). C'est un vrai fil de SMS,
   dont l'autrice ne prend que la forme : ni le caractère, ni les sujets. Il est vide par défaut. Avec le fil « Léa,
   Lisbonne », elle prenait le ton autoritaire de Léa, et sans lui elle atteint déjà l'étalon.
7. *Toutes ses réponses passent par l'autrice*, même les courtes. Une réponse récrite qui dépasse deux fois le premier
   jet plus 120 caractères a dérivé : le premier jet part. Le polisseur dit ce qu'on garde (`Polisher` rend
   `(consigne, message, garder)` et reçoit la persona rendue).

**Mesures** (banc de conversation, deux mesures par réglage, ±2 points de bruit) :

| Réglage | Score |
|---|---|
| Sonnet seul (main) | 58,3 |
| Sonnet, seconde passe Sonnet low (relecture, ADR 0112) | 62,0 |
| Sonnet, seconde passe Opus (relecture) | 64,4 |
| Opus partout, seconde passe Sonnet low | 64,2 |
| Sonnet, autrice Opus (sans fil de référence) | 63,4 |
| Une réécriture par Opus faite pour plaire au juge (plafond du juge) | 71,0 |

Le juge Opus plafonne : même des répliques réécrites exprès pour lui n'obtiennent que 71. L'étalon est donc la
propriétaire. Elle a jugé chaque étape, d'abord sans le moteur puis dans le moteur :

| Étape | Son avis |
|---|---|
| Le fil écrit d'un coup par Opus, puis avec le portrait de Mika | 100 % |
| Tour par tour, face à un Adrien joué par Haiku | hors jeu : l'interlocuteur simulé raconte mal |
| Tour par tour, une réplique à la fois | 80 % (une chute à chaque message) |
| Quatre échanges d'avance | 90 % |
| + réactions variées et émojis, puis dans le moteur (tête Sonnet, autrice Opus) | « 100, c'est ce que je cherche » |

Dans le moteur, face à un Adrien joué par Opus :

| | Longueur moyenne | Avec une question |
|---|---|---|
| L'étalon (Léa) | 29 | 10 % |
| Opus partout, seconde passe (avant) | 96 | 27 % |
| Autrice, quatre échanges d'avance | 53 à 58 | 17 à 22 % |

**Conséquences.**

- Le rôle `polish` sert désormais à écrire ses messages, plus seulement à les relire. Son meilleur modèle est Opus,
  qui ne lit que le portrait et le fil : bien moins de contexte que la voix entière, sans outils.
- Sans modèle pour `polish`, rien ne change : le premier jet part, comme avant.
- Le juge du banc n'est plus l'arbitre final : il ne distingue plus les meilleurs réglages, et l'étalon est le goût
  de la propriétaire (ses 👍/👎, ADR 0113, et ses conversations réécrites).
- Le banc de conversation doit jouer Adrien avec Opus (`--adrien opus`) : Haiku raconte trop mal pour juger sa voix.
- À suivre : des émojis parfois un peu fréquents, et quelques relances par question quand on lui raconte une
  histoire.
