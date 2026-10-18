# 0116 — Le mode pro : un travail demandé dans le chat

**Contexte.** Depuis l'autrice (ADR 0114), sa parole en chat est faite pour la conversation : courte, en bulles,
avec son caractère, réécrite par une seconde passe et lue à voix haute. Le 2026-10-16, la propriétaire demande « un
mode pro, un peu un mode Claude Code activable dans le chat » : quand elle lui demande un travail dans ce mode,
l'autrice est coupée, la matrice de personnalité aussi, et l'on voit en temps réel les outils qu'elle exécute.

**Décision.**

1. *Le mode est choisi par message.* La trame `chat` porte `mode: "pro"` ; la perception le garde
   (`PerceptionReceived.mode`), donc une réponse reprise après un redémarrage ou une supplantation garde son mode.
   Seule une connexion **authentifiée d'opératrice** peut le demander : ailleurs, le message est ordinaire, sans
   erreur. Le dernier message du tour décide (une rafale reçoit une réponse, dans le mode de son dernier message).
2. *Un mode plie la politique de l'épisode* (`kernel.episode.EpisodeMode`, déclarés par la composition dans
   `app/composition.py::modes()`, passés au pipeline par `KernelDeps.modes`). Le runtime n'en nomme aucun. Le mode
   pro vaut pour `REPLY` :
   - son rôle de modèle à lui, `pro`, qui retombe sur `reply` : on peut lui donner un modèle plus fort ;
   - sa persona en profondeur `pro` (`self.persona._pro`) : son nom, sa description, ce qui est vrai d'elle, sa
     langue et sa nature ; ni portrait, ni ton, ni exemples de sa voix, ni tempérament ;
   - ses sections `affective` (sa consigne de style, son humeur, ses pensées, ses besoins…), `inner` et `last`
     (« TA RÉPONSE ») coupées ;
   - ni relecture ni seconde passe ;
   - la consigne `expression.pro` à la suite de celle de ses outils : faire le travail avec ses outils, ne rien
     affirmer qu'un outil ou sa mémoire ne lui a donné, répondre à l'écran en Markdown, sans balises ;
   - de la place : 24 tours d'outils, 8 192 jetons, 15 min.
3. *Sa réponse est du Markdown.* L'analyse d'une parole de chat resserre les espaces, ôte l'indentation et prend
   `[INDEX]` pour un jeton : en mode `markdown`, les blocs de code, le code en ligne et l'indentation des lignes
   passent à l'abri (`pipeline._shield`). Ses balises éventuelles se retirent toujours.
4. *Ses outils se voient en direct.* La boucle d'outils accepte un regard (`run_tool_loop(watch=…)`) : un outil qui
   part, le même fini (refusé compris), ce qu'elle écrit entre deux appels. Le pipeline les passe au port
   `activity` (`ports.delivery.Activity`), puis la fin de l'épisode. Le concentrateur web en fait des trames `tool`,
   envoyées aux seuls écrans regardés et authentifiés d'opératrice de la personne. Arguments et résultats sont
   bornés à 2 000 caractères. **Rien n'en est gardé** : ni journal, ni historique, ni rattrapage. Ces textes n'ont
   pas de sujets déclarés et l'oubli ne les atteindrait pas (ADR 0024, 0108). Les clients les gardent en mémoire
   seulement.
5. *Le fil garde le mode.* `rt.Utterance.mode`, et la colonne `mode` de la table du fil (version 8). L'historique
   porte `mode` sur les deux messages et, pour sa réponse, les noms de ses outils (`tools`, ADR 0108). La `speech`
   porte `mode` ; une réponse pro ne se dit pas à voix haute (`speak: false`, `voice_reason: "pro"`) et forme une
   seule bulle (une ligne vide ne la coupe pas).
6. *Dans les clients* (web et Android) : un interrupteur « Pro » près du champ, pour une opératrice, retenu sur
   l'appareil ; la carte de travail en direct sous son message, repliée au-dessus de la réponse quand elle arrive ;
   la bulle pro rendue en Markdown sans risque ; l'historique avec la ligne de ses outils.

**Conséquences.**

- Elle reste elle-même : sa mémoire, ce qu'elle sait de la personne, ses projets et ses outils sont là. Sa voix de
  chat, son caractère et son humeur ne colorent pas un travail. Ses réponses pro restent dans le fil, et une
  conversation ordinaire qui suit les relit.
- Sans modèle déclaré pour `pro`, c'est celui de `reply` qui travaille (le repli d'un rôle, jamais d'un fournisseur :
  ADR 0073).
- Un message envoyé pendant qu'elle travaille la supplante, comme d'ordinaire : son travail se recompose avec lui
  (les écritures de ses outils sont dédoublonnées par le tour) et une nouvelle carte commence.
- La trame `done` et la `speech` peuvent arriver dans les deux ordres : la parole part de la file de sortie dès son
  commit, la fin après le règlement.
- Tests : `tests/unit/test_pro_mode.py` (le noyau, avec le contre-exemple ordinaire, la persona, l'abri du code, un
  regard en panne), `tests/protocol/test_pro_mode.py` (le chat : l'opératrice, la non-opératrice).
