# 0093 — Le modèle lit la personne ; ses émotions ont des facettes

**Contexte.** Deux modules lisaient les émotions des gens dans des listes de mots :
- `others/tone.py` (« triste », « marre », « génial », émojis, majuscules, « événements graves » par expressions
  régulières) donnait la valence et l'agitation de chaque message, d'où l'inquiétude pour une amie, la contagion, la
  surprise, le soulagement et `memory.hard_times` ;
- `self/worth.py` repérait par expressions régulières insultes, compliments, mercis et excuses, d'où son estime, le
  pardon de ses pensées et son hostilité.

C'était contraire à la règle posée par l'utilisateur (une émotion se juge par l'IA, en facettes, jamais par des mots),
et faux en français : le ton fait tout. « T'es con » d'une proche qui rit n'est pas celui d'un inconnu, « petit con »
est rarement une insulte, « grosse conne » presque toujours. Et sa propre balise n'avait qu'une émotion, alors que la
mémoire jugeait déjà en facettes (ADR 0083) : son ambivalence ne pouvait pas se déclarer.

**Mesure avant de trancher** (`tools/banc_lecture`, 62 messages français piégeux avec leur contexte — qui écrit,
quel lien, ce qui vient d'être dit —, Haiku par la CLI Claude Code, la vraie consigne et le vrai analyseur) :

| | geste envers elle | ton de la personne | événement grave |
|---|---|---|---|
| ancienne lecture des mots | 54/62 | 42/62 | 57/62 |
| le modèle (Haiku) | 61/62 | 57/62 | 62/62 |

La liste de mots ne voyait pas « grosse conne » d'un inconnu mais prenait « t'es bête toi » ou « t'es nulle, je
t'adore » d'une amie pour des insultes, lisait « super, merci pour rien » comme joyeux, ratait la détresse à demi-mot
(« j'ai plus envie de rien, je sers à rien », « ce serait plus simple si je disparaissais ») et inventait des drames
(« j'ai cru que j'allais faire une crise cardiaque », le décès du père d'un collègue). Le modèle s'est trompé une fois
sur un geste (« petit con va » lu comme un compliment taquin) et quatre fois sur une nuance de ton discutable.

**Décision.**

1. *Le modèle lit la personne.* En répondant, il écrit une balise que la personne ne voit pas :
   `[EN_FACE: sad 0.7, anxious 0.3 | geste : excuses | grave : rupture]` — ce qu'elle ressent en facettes (« rien »
   si rien ne se lit), son geste envers Mika s'il est net (merci, compliment, excuses sincères, mots blessants — ni une
   politesse, ni une taquinerie), un événement grave qui la touche (deuil, maladie ou accident, rupture, perte de
   travail, détresse). `vocab/reading.py` range ce qu'il a choisi (une catégorie qu'on lui a donnée, comme
   `emotion_named` range un nom d'émotion) ; il ne lit jamais le message de la personne. `expression.parse` retire la
   balise du texte livré et l'annote (`their_feeling`). Sans balise, rien ne se lit — jamais une lecture neutre
   inventée.
2. *Les jugements restent enregistrés, leur source change.* Le runtime interprète désormais aussi sa réponse, juste
   après l'avoir écrite (`EpisodeRunner.interpret`, branché par le démarrage sur `Bootstrap.interpret` : un crochet
   générique, le runtime ne nomme aucune faculté). `others` en tire `others.read` (`felt`, `grave_kind`, valence et
   agitation par `vocab.affect.felt_pad` — l'intensité compte : « triste 0,8 » pèse plus que « triste 0,2 »), `self`
   en tire `self.touched`. La contagion reprend la facette dominante de la personne (une amie furieuse contre son
   patron lui laisse un peu de colère, plus de l'anxiété). Les lectures d'avant, enregistrées, se rejouent telles
   quelles.
3. *L'ordre a changé, et ce qui en dépendait suit.* La lecture d'un message arrive avec la réponse, plus avant elle :
   - la section « CE QUE TU PERÇOIS DE SON ÉTAT » dit le ton habituel de la personne (« d'habitude, Alice t'écrit sur
     un ton plutôt léger ») pour que le modèle juge lui-même si ce message lui ressemble, et « ces derniers temps » ce
     qui tranche ; les indices de forme ont disparu ;
   - une lecture qui suit la réponse (`after_reply`) allège tout de suite ce qui concerne la personne si elle a
     retrouvé son ton, et ne referme jamais l'inquiétude que la réponse à ce même message vient d'ouvrir ;
   - « elle t'a présenté ses excuses » se dit à la réponse suivante (le modèle lit les excuses dans le message même) ;
   - le courrier se retire d'une conversation lourde dès la réponse suivante.
4. *L'au revoir n'est pas une émotion.* « Bonne nuit », « à demain » se reconnaissent à leur forme
   (`vocab/farewell.py`), à l'arrivée du message, pour que la clôture vaille même si elle se tait : événement
   `others.farewell`. Les heures où chacun écrit se notent sur chaque message reçu ; les initiatives envers ses amies
   (encourager, demander comment ça s'est passé, souhaiter, prendre des nouvelles) passent en revue celles qui lui
   ont écrit (`others.heard`), plus seulement celles dont elle avait lu le ton.
5. *Ses émotions ont des facettes.* `[EMOTION: sad 0.6, love 0.3]` (la forme d'avant reste lue, à l'identique,
   intensité par défaut comprise) ; `Declared.facets`, encodage rétrocompatible (`sad:0.600,love:0.300`). Son humeur
   et sa posture visent le mélange de ses facettes (`physics.blend`, pondéré par les intensités ; une seule facette :
   exactement la cible d'avant) ; son visage montre ses deux premières facettes déclarées (son ambivalence, jugée par
   le modèle, plus calculée) ; une facette triste ou inquiète suffit à l'inquiéter (`others`) ou aux temps durs
   (`memory`), même si elle n'est pas la plus forte.
6. *La date d'un deuil.* Elle pèse par ce que la personne en ressent (le ressenti jugé par la relecture) — une date
   annuelle vécue douloureusement, une séparation, pèse aussi — ou parce qu'elle parle d'une mort, dans le texte que
   la relecture a écrit : un fait, pas une émotion devinée, le filet qui garde de souhaiter « l'anniversaire de la
   mort de son père ».
7. *Une garde.* `test_reading.py::test_nothing_in_her_code_guesses_an_emotion_from_words` : les deux modules ne
   reviennent pas, et aucune chaîne du code de ses facultés, plugins, runtime ou application ne cherche un mot
   d'humeur ou d'insulte (trois listes de mots qui ne devinent rien sont nommées, avec ce qu'elles font). Le
   simulateur, qui joue le modèle, en a le droit : sa doublure écrit `[EN_FACE: …]`.

**Conséquences.** Modules retirés : `faculties/others/tone.py`, `faculties/self/worth.py`. Nouveaux :
`vocab/reading.py`, `vocab/farewell.py`, `tools/banc_lecture/` (le banc), `tests/fixtures/reading.py` (un test joue
le modèle). `others.read` gagne `felt`, `grave_kind`, `brief`, `after_reply` ; événement nouveau `others.farewell`
(libellé) ; `others` en version 5 (`last_felt`, heures sur le message reçu). `Declared.facets`, `felt_pad`,
`physics.blend`, `mood_target_of`, `stance_target_of`. `contracts.expression.READING_ANNOTATION`. Consigne de style
réécrite (`expression.style` : les deux balises) ; phrases retirées (`others.cues.*` sauf `short`, gardée pour le
journal d'avant ; `others.state.cues` ; `others.grave.*`), nouvelles (`others.state.usual_light`, `usual_heavy`).
Les tests qui vérifiaient la liste de mots sont partis avec elle ; ceux de bout en bout font déclarer au modèle ce
qu'il lit. Cibles : `tests/unit/test_reading.py` ; 18 mutations, toutes rouges.

**Ce qui n'est pas fait.** Un message auquel elle ne répond pas (dans un salon sans lui être adressé, ou quand elle se
tait) n'est pas lu. Le modèle juge seul : le banc est à relancer quand la consigne ou le modèle changent, et à élargir
avec les exemples de l'utilisateur. Le banc ne passe que par la CLI Claude Code (pas encore par un fournisseur
configuré de Mika).
