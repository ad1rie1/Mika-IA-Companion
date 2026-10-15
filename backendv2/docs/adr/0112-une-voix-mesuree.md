# 0112 — Une voix mesurée : le banc de conversation et la relecture avant envoi

**Contexte.** Le 2026-10-14, la propriétaire trouve que Mika « ne parle pas humainement ». Elle relève plusieurs
défauts dans de vraies conversations avec Sonnet :
- un interrogatoire : chaque réplique finit par « ceci, ou cela ? » ;
- des redites de ce qu'elle vient de dire ;
- un ton de guichet (« Dis-moi, je regarderai si tu veux ») ;
- des commentaires sur sa recherche (« c'est la page de flash info de RTL… je n'ai lu que le début ») ;
- la fiche d'un jeu récitée à un joueur.

Les corrections de prompt une à une ne tenaient pas. Il fallait mesurer, en conditions réelles. La propriétaire
demande de générer des conversations, de les faire juger par Opus selon son paramétrage et son côté humain, d'en tirer
un score, puis d'améliorer en boucle à partir des traces de contexte.

**Décision.**

1. *Un banc de conversation* (`tools/banc_conversation/`).
   - **Les conversations.** Le vrai noyau parle avec sa persona, ses facultés et ses prompts. Sa voix est celle du
     service : Sonnet par la CLI Claude Code, effort « high ». Ses outils passent par le relais MCP, servi par le banc
     comme le serveur le monte. En face, un Adrien simulé par Haiku : ses vrais messages lui servent de modèle
     d'écriture, jamais de sujet. Il y a 12 scénarios, dont 3 réservés, jamais regardés pour régler.
   - **Le juge.** Opus note chaque réplique de 0 à 10, avec ses défauts, et six critères d'ensemble : naturel,
     écoute, personnalité, variété, justesse, tact. Son étalon, ce sont les réponses que la propriétaire a trouvées
     pas naturelles. Elle a validé son jugement sur une conversation, en trouvant le score global un peu haut.
   - **Le score** sur 100 : 40 % la note moyenne des répliques, 30 % la moyenne des critères, 30 % le pire critère.
     Un défaut qui revient tire ainsi l'ensemble vers le bas.
   - **La reproductibilité.** Chaque mesure tourne sur une copie figée du code, et une variante ne modifie que cette
     copie (`--variante`). Chaque réplique renvoie à l'appel qui l'a écrite (`appels.jsonl`), donc à son prompt
     entier.
2. *Sa réponse relue avant de partir.* Le pipeline gagne une étape générique, `reviewers`, que la composition branche
   sans que le runtime nomme de faculté. Le relecteur d'expression (`expression.review`) repère les tics sur le
   brouillon même, sans modèle :
   - une question à options, ou plusieurs questions ;
   - la même ouverture que deux des trois messages précédents ;
   - un début qui redit les mots de la personne ;
   - cinq mots déjà dits dans un de ses derniers messages, ou six mots recopiés de son portrait ;
   - un second bonjour, un second au revoir ;
   - une réponse longue à un message court ;
   - une question encore, quand ses deux derniers messages en posaient déjà.

   Sur une remarque, un seul nouvel appel est fait : la remarque (« RELIS-TOI ») est glissée juste avant la fin de
   son état interne, et la nouvelle réponse remplace la première. Jamais après des outils, car un nouvel appel les
   referait. La trace de l'épisode garde le premier jet et la remarque (`relecture`). Elle réécrit 15 à 20 % de ses
   réponses, et les réponses réécrites sont jugées aussi bien que les autres, ou mieux.
3. *« TA RÉPONSE », le dernier mot de son état interne.* Le composeur gagne une bande « en dernier » (`LAST`), juste
   avant le message. Le rappel y dit de réagir en personne, de s'intéresser à ce que vit la personne (une vraie
   question, ouverte, une à la fois), de ne pas analyser, de ne pas conseiller sans qu'on le demande, et de ne pas
   redire. Il y ajoute « réponds court » à qui écrit en quelques mots, et un mot ciblé pour un merci ou un au revoir.
   Il finit par « Ne fais pas de ce qu'on te dit une vérité générale ni une analyse : réagis à la personne, pas au
   sujet » (voir l'ablation, plus bas).
4. *Sa persona.*
   - Le ton n'est plus « sobre » : cette sobriété tenait la voix trop expressive de Gemma, mais rendait Claude plat.
   - En chat, elle prend le registre de la personne, et elle parle d'elle au féminin.
   - Des exemples de sa voix (`PersonaDoc.samples`) apparaissent en conversation seulement, jamais dans un mail ni
     dans son journal. Ils sont tirés de ses répliques les mieux jugées au banc.
   - Elle connaît ce qu'elle lit et se fait raconter le reste.
   - « Déjà raconté » cite ce que ses derniers messages disaient d'elle.
5. *Une matrice de personnalité qui s'entend.* Avant cette décision, avec les profils réfléchie, solaire et kuudere,
   elle parlait presque pareil : le texte de sa persona l'emportait sur ses curseurs. Désormais :
   - le ton de sa persona ne dit plus que le registre (naturelle, jamais un assistant) et renvoie au tempérament
     pour ce qu'elle montre et comment elle réagit ;
   - ses exemples montrent le registre, pas le caractère ;
   - « peu de points d'exclamation » quitte ses façons de parler ;
   - dans « TA RÉPONSE », ses trois traits les plus marqués (à 20 % ou moins, ou à 80 % ou plus) sont traduits en
     façon d'écrire dans un chat (`expression.answer.traits` : « tu montres peu : des phrases courtes et neutres, ni
     point d'exclamation ni « haha »… »). Ce rappel prime sur les exemples de sa voix.
6. *L'API à la place de la CLI, possible et mesurée.* `ClaudeBackend` gagne l'espace de travail (`workspace`, pour une
   clé « sk-ant-usr- ») et l'effort de réflexion. Celui-ci s'appuie sur la réflexion adaptative native du SDK
   Anthropic (`thinking`, `output_config`), comme `--effort` pour la CLI. `mika llm backend --workspace` déclare
   l'espace de travail.
7. *Une seconde passe qui rend sa réponse naturelle* (l'idée de la propriétaire : un premier appel fait tout le
   travail, un second rend la réponse naturelle au vu du fil, sans changer ce qu'elle ressent).
   - Une étape générique du pipeline, `polishers`, après la relecture, sur ses réponses (`REPLY`). Le relecteur
     d'expression (`expression.polish`) donne la consigne : le texte seul, les derniers messages du fil, ses traits
     marqués ; rien à ajouter (ni fait, ni idée, ni question), seulement couper ou alléger (une vérité générale, une
     analyse, ses mots à lui redits, une question de trop, un conseil qu'on ne demande pas, ce qui sonne rédigé).
   - Le modèle du rôle LLM `polish`, **sans repli** : la passe ne se fait que si l'opératrice lui donne un modèle
     (`mika llm route polish …`) ; une installation ne paie pas un second appel de sa voix sans l'avoir choisi.
   - Ses balises restent celles du premier jet : ce qu'elle ressent, ce qu'elle a lu de la personne ne changent pas.
     Ses outils ne se refont pas (la passe ne voit que le texte) : elle vaut aussi après des outils.
   - Une panne, un silence ou une réponse qui s'allonge : le premier jet part tel quel.
   - Ses traits marqués lui sont dits « pour ne pas les lui enlever, jamais pour en rajouter » : dits comme une
     consigne (« qui doit rester dans le message »), la passe caricaturait — solaire passait de 7 % à 79 % de
     messages à « ! », un émoji en plus ; kuudere devenait sèche.
8. *Sa réponse en plusieurs bulles.* Comme quelqu'un qui écrit vraiment, la passe peut l'envoyer en plusieurs
   messages (trois au plus), séparés par une ligne vide. Le journal garde **une** réponse — un énoncé, un
   `message_id`, une notification, un souvenir, une humeur — ; les clients la montrent bulle par bulle, « Mika
   écrit… » entre deux, au rythme de la frappe (web : `ui/bubbles.ts` ; Android : `BubbleContent.parts`, sa voix
   les dit l'une après l'autre). En faire plusieurs énoncés aurait touché une trentaine d'endroits (son humeur et
   ses besoins comptés deux fois, des échanges coupés dans sa mémoire, l'attente d'une réponse perdue, trois
   notifications, le fil montré au modèle). Une ligne vide n'est plus une « réponse longue » pour la relecture.

**Les mesures.** Sonnet, sur les 9 scénarios regardés, sauf mention. Une même configuration varie de ±2 à 3 points
d'une passe à l'autre, et de ±9 par scénario.

| Étape | Score |
|---|---|
| Départ (base-1) | 55,4 (réservés 54,9) |
| « TA RÉPONSE » en fin d'état interne | 59,0 |
| Rappel allongé | 55,6 |
| + relecture avant envoi | 61,2 / 62,2 (deux passes) |
| + contrôles du bonjour, de l'au revoir, de la longueur et de l'écho | 59,5 / 60,5 |
| « Déjà raconté » étendu à la conversation | 60,6 |
| Curiosité pour la personne | 60,1 |
| + exemples tirés de ses meilleures répliques, copie du portrait repérée | 62,5 |
| **Configuration finale, 12 scénarios** | **58,9 (regardés 58,0, réservés 61,6)** |

Les mêmes configurations essayées autrement :

| Variante | Score |
|---|---|
| Effort « medium » / « low » (au lieu de « high ») | 57,5 / 58,3 |
| Matrice sans traits neutres | 61,9 |
| Matrice en phrases, sans pourcentage | 60,9 |
| Aucun outil en conversation | 63,2 |
| Préface contre les injections de la CLI | 58,3 |
| Sonnet par l'API (réflexion « high ») | 60,0 |
| Opus par la CLI | 66,2 |
| Opus par l'API | 63,4 |

**Conséquences.**

*Ce qui a compté.*
- Sur les scénarios réservés, le score passe de 54,9 à 61,6 : les gains se généralisent.
- Le plus gros levier est la relecture avant envoi (+6). Un tic du modèle se voit sur le brouillon ; une consigne de
  prompt ne le retient pas.

*Ce qui n'a rien changé ou a fait pire.*
- Avec Sonnet, les leviers du prompt plafonnent vers 60–63.
- La forme de la matrice, retirer les outils et l'API au lieu de la CLI ne changent rien de mesurable.
- Moins de réflexion fait pire.

*Le choix du modèle.* Opus fait mieux, de +4 à +6, mais c'est un choix de coût et de lenteur que la propriétaire
garde.

*Les injections de la CLI.* La CLI Claude Code ajoute, même avec `--system-prompt` :
- « You are a Claude agent, built on Anthropic's Claude Agent SDK. » avant son prompt ;
- un rappel `userEmail` (l'adresse du compte) avant le message ;
- un bloc « # Environment » après le message.

Aucun réglage ne les retire : `CLAUDE_CODE_SIMPLE` casse l'abonnement. On ne les retire pas par un mandataire, car
ce serait contourner l'abonnement. Leur effet mesuré est nul. `tools/banc_conversation/audit/mandataire.py` sert à
les auditer. Seule l'API (une clé) donne un prompt sans ajout.

*La cohérence de la matrice* se mesure par une reconnaissance à l'aveugle (`banc.py reconnaitre`) : Opus retrouve
sous quel profil une conversation a été vécue. Entre solaire et kuudere (hasard : 50 %) :

| Version | Profils reconnus |
|---|---|
| Persona écrite pour un seul caractère | 66 % |
| Traits traduits en façon d'écrire | 88 % |
| + sans la règle des exclamations, traductions observables | 94 % |
| + sans mot imposé (« haha » était devenu un tic) | 94 % |

Entre les trois profils, le juge range presque tout chez réfléchie, quelle que soit la version (36 à 40 %). Le profil
réfléchie livré coche lui-même l'expressivité (70 %) et la curiosité : il ressemble à tout.

Ce que la cohérence change aux voix, en marqueurs objectifs :

| Profil | Longueur moyenne | Messages avec « ! » | Questions |
|---|---|---|---|
| solaire | 246 caractères | 7 % | — |
| réfléchie | ~200 caractères | — | 47 % |
| kuudere | 160 caractères | 0 % | 42 % |

Le prix : environ 2 points de naturel en moyenne (57–58 contre 58–61), à la limite du bruit. Un mot imposé dans une
consigne devient un tic : la traduction d'un trait dit une manière, jamais un mot à placer.

*L'ablation d'un prompt* (`tools/banc_conversation/ablation.py`). Trois appels réels mal jugés sont rejoués tels
quels : « c'est le piège du métier… » (3/10), une reformulation de psy (4/10), des conseils de guichet (4/10). On
retire ou modifie un bloc à la fois, avec 6 à 8 tirages par version, notés à l'aveugle par Opus.
- **Retirer un bloc** (la matrice, les outils, les balises, l'état interne, les exemples, le portrait, ou tout à la
  fois : 4 700 caractères au lieu de 17 400) ne change rien au-delà du bruit. Le prompt minimal redonne la même
  maxime.
- **Le prompt nu** d'une ligne fait bien pire (2,7 à 5 sur 10 : des pavés de conseillère, 540 caractères). Le défaut
  vient du modèle, et son prompt le corrige déjà en partie.
- **Ce qui aide** : une phrase ajoutée en dernier, « vérité générale ni analyse » (+0,6 à +0,9 sur 10, maximes de
  62–100 % à 25–50 %). Aussi, deux traits de réfléchie réécrits : « une remarque réfléchie plutôt qu'une réaction à
  chaud » demandait une maxime, « la question qui creuse » une question à chaque fois. Réécrire toute la consigne ne
  vaut pas cette phrase ajoutée en dernier.
- **Ce qu'aucune version ne retient** : la question finale, présente dans 88 à 100 % des réponses. La relecture la
  repère donc à la troisième d'affilée.

En conversation entière (v9, 9 scénarios), le score ne bouge pas (57,9 → 57,2, dans le bruit), mais le défaut visé
recule : « ton écrit » de 21 à 10, note moyenne des répliques de 6,17 à 6,30. En contrepartie, « plat » passe de 3 à
10. Le premier défaut est désormais un thème qu'elle ressort à chaque message (« le coussin » quatre fois, « devant
tout le monde » quatre fois). Une réponse isolée ne le montre pas, et un mot répété ne le trahit pas assez bien : il
attrape aussi le sujet même de la conversation.

*La seconde passe* (Sonnet, effort « low », ~4 s de plus par réponse), mesurée d'abord sur les trois appels de
l'ablation (premier jet 5,46 · Sonnet low 6,09, aucun ajout · Haiku 6,46 mais trois ajouts sur 24 et du concret
coupé), puis en conversation entière :

| Profil | Sans la passe | Passe, traits « à garder » | Passe, traits « à ne pas enlever » |
|---|---|---|---|
| réfléchie | 57,2 | 60,3 | 60,9 |
| kuudere | 57,9 | 64,8 (sèche) | 59,5 |
| solaire | 56,4 | 53,2 (« ! » dans 79 % des messages, surjeu) | 57,1 |

La note moyenne des répliques monte pour les trois profils (réfléchie 6,30 → 6,55, kuudere 6,17 → 6,47, solaire
5,94 → 6,24), et la matrice s'entend mieux : à l'aveugle, solaire contre kuudere 18/18 (avant : 94 %), entre les trois
profils 51 % (avant : 37 %).

Avec les bulles (réfléchie, v12) : 60,4, dans le bruit de v11 (60,9) ; la passe découpe 41 réponses sur 60, le plus
souvent en deux (une réaction, puis une question ou un bout d'elle) ; le juge note chaque bulle à part (6,61 en
moyenne, « aucun défaut » pour 53 d'entre elles) et le naturel monte à 6,8.

Avec la passe, « ton écrit » recule encore (réfléchie : 21 → 10 → 5) et la variété, le pire critère, remonte (4,6 →
5,4). La propriétaire préfère la version courte à la version spirituelle (« C'est quoi comme réunion ? » plutôt que
« …qui te donne autant envie ? ») ; le juge, lui, compte « plat » comme un défaut — à lui montrer avant de conclure.

*À mesurer pour tout changement de sa voix.* Tout changement de prompt ou de modèle se mesure au banc avant d'être
proposé : deux passes quand l'écart est petit, et un regard sur les scénarios réservés.
