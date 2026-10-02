# 0032 — L'affect sur trois échelles : le moment, la journée, la relation

**Contexte.** L'audit psychologique du 2026-10-01 (constats PSY, PRM, EDG) a mesuré ce que l'affect faisait vraiment :

- **Une impulsion visait un point mesuré depuis l'origine** de l'espace PAD, alors que le repos est positif (plaisir 0,26–0,37 selon l'heure). Une balise positive légère tirait donc *sous* le repos : à 15 h, `happy:0.3` se lisait « lasse », `amused:0.4` « mélancolique », `neutral` « seule ». Quatorze soirées chaleureuses laissaient un regard de −0,04 à +0,02, et personne ne devenait « proche » par la chaleur (PSY-1, PSY-27).
- **Une dispute effaçait un mois d'amitié** : l'ancre absorbait 15 % de chaque déclaration, quelle que soit l'histoire (PSY-3). **Consoler refroidissait** : la tristesse partagée se fondait vers sa propre ancre (PSY-4). La guérison était symétrique, demi-vie de 3 jours : l'affection s'évaporait en une semaine, la rancune envers un troll en un jour (PSY-10).
- **L'horloge inventait des émotions** : le repos saute aux débuts de phase, l'humeur le rattrapait en ~23 min, et le ressenti lisait cet écart (« curieuse » 0,48 à 18 h 01, au-dessus du seuil de débordement) (PSY-5).
- **L'humeur ne durait qu'une vingtaine de minutes** : une après-midi de deuil était oubliée deux heures après (PSY-6).
- La chaleur et la rancune se mesuraient contre le repos **de l'instant** et variaient avec l'heure (PSY-9). La balise déclarée disparaissait d'un coup après 20 min (PSY-11) ; le visage, lui, passait 3 s après la réplique à une troisième émotion effondrée (EDG-16). L'évaluation « retour » appliquait l'échelle deux fois (PSY-23). « Bien ancrée » se déclenchait sur deux tours anodins (PSY-8).
- La prose mentait sur son objet (« Envers cette personne, tu te sens fière » pour sa fierté à elle, PRM-3), parlait mécanique (« une nuance de en colère », « mono-couleur », PRM-16) et manquait aux séances de travail (PRM-26).
- La balise et la prosodie n'étaient reconnues que sous leur forme canonique : débris de markdown, `60%`, `[EMOTION:triste:0.6]`, `[PAUSE:500ms]`, `[SOUPIR]`, `*rit*`, « Mika : », `<thinking>` partaient chez la personne (P3–P9, EDG-19).

**Décision.**

1. *Une impulsion vise le rayon repos → émotion* : `lerp(repos, ancre(e), intensité)`. Pour l'humeur, le repos est celui de l'instant (jumeau + fond, ci-dessous) ; pour une posture, le repos de la personne ; pour l'ancre, le repos moyen. Une évaluation vise l'émotion pleine, l'intensité ne réglant que le gain (une seule échelle). `neutral` ne produit **aucune** impulsion et aucune ligne de posture.

2. *L'humeur a trois couches, toutes linéaires et en forme close.*
   - **Le repos jumeau** : un oscillateur sans impulsion qui suit le repos commun. Le ressenti se mesure contre lui. Le saut de repos à un début de phase touche le jumeau comme la position : l'écart n'en garde rien.
   - **L'émotion du moment** (`gap`) : un oscillateur libre, d'une constante de temps d'environ 23 min. Ce qui déborde (la porte d'initiative) se lit sur cette couche seule.
   - **Le fond de la journée** (`fond`) : un passe-bas de l'émotion du moment, `f' = (poids·émotion − f)/τ`, avec τ d'environ 5 h d'éveil (de 8 h à 3 h selon la résilience), un poids de 0,5 et un plafond de 0,2. Il fige pendant le sommeil et perd 60 % au réveil ; le reste colore le matin. Sa forme close est l'exponentielle d'une matrice triangulaire par blocs ; un test la confronte à une intégration fine.

   Le fond colore la prose et le ressenti (une après-midi triste se lit encore vers 19 h 30). Quand l'humeur est presque au repos, il se dit « avec un petit reste de tristesse de tout à l'heure ». Ce reste est nommé par l'émotion récente qui l'explique le mieux, lue contre le repos moyen : lue contre le repos du soir, une colère de l'après-midi devenait « pensive ».

   Le fond ne pousse pas à parler. Le poids et le plafond sont calibrés par la solitude d'une journée vide, avec un vide toutes les dix minutes : le fond y monte à environ 0,16. Avec un poids de 1, il doublait le ressenti, qui atteignait la porte de détresse (0,5). Elle cherchait alors du réconfort après sept heures seule, ce qu'un test du lot social (« une seule ») refusait à juste titre.

3. *Ce qu'une relation installe se mesure depuis son repos moyen sur 24 h* (chaque teinte pesée par la durée de sa phase), jamais depuis l'heure qu'il est. L'ancre est stockée comme cet écart. Le repos d'une posture est le repos commun de l'instant plus 0,6 × l'ancre. L'ancre guérit en ligne droite : le cas général est une exponentielle exacte, sans découpage en journées.
   - **La part fondue diminue avec l'histoire** : α = 0,15 / (1 + jours de contact / 14).
   - **L'empathie rapproche.** Une tristesse, une peur, une solitude, une anxiété, une mélancolie ou une nostalgie dites à quelqu'un tirent l'ancre vers la tendresse, depuis là où en est la relation (`lerp(ancre, LOVE, 0,3·i)`). Elle ne refroidit jamais une relation chaleureuse.
   - **La guérison est asymétrique.** Une ancre chaleureuse guérit cinq fois plus lentement (~15 jours). Une ancre hostile guérit `(1 + déclarations hostiles / 6)` fois plus lentement, avec une demi-vie d'au plus 21 jours. Un froid ordinaire garde la demi-vie de base.
   - **L'attachement** (`bond`, de 0 à 1, jamais négatif) gagne `0,01 × intensité × (1 − bond)` à chaque déclaration chaleureuse ou empathique. Sa demi-vie est de 60 jours. Il entre au regard pour 0,3 × bond et multiplie l'hostilité par `1 − 0,6 × bond`.
   - **La méfiance.** Une personne qui n'est ni amie ni proche et dont l'hostilité dépasse 0,3 laisse une méfiance plancher de 0,1 pendant 14 jours.

4. *Ce qu'elle a déclaré décroît* au rythme de sa posture : `i·exp(−Δ/τ)`. La position prend le relais dès qu'elle en dit plus, et la balise s'efface sous un plancher de 0,1 (la fenêtre de 20 min est retirée, `retired_params`). Le **visage** (`FACE`) montre la balise de la dernière réplique dans cette décroissance, environ 20 min pour une balise à 0,8, puis revient à la lecture des positions.

5. *Une posture « installée »* demande un écart d'au moins 0,25 au repos et au moins deux déclarations récentes dans le même sens. « Ça ne passera pas en deux minutes » ne s'ajoute que si l'ancre porte ce fond.

6. *La prose* sépare trois choses.
   - **Sa balise** : « À l'instant / Tout à l'heure, en lui répondant (en lui écrivant), tu étais … ».
   - **Le moment** : « Avec « X », en ce moment, tu te sens … ».
   - **Le fond relationnel**, seulement s'il est chaleureux (« vos échanges ont installé de la tendresse ») ou hostile (« au fond, tu restes plutôt en colère »), ainsi que l'attachement (« Tu tiens à « X » »).

   La deuxième couleur s'écrit avec un nom : « Et en dessous, il y a un peu de colère ». La cause d'une humeur vient de la dernière impulsion qui pousse dans son sens. Les codes deviennent des phrases génériques, sans jamais nommer un tiers : « Ça vient de votre échange » si c'est avec la personne en face, sinon « d'une autre conversation ». Sans cause connue : « sans trop savoir pourquoi ». L'humeur entre aussi dans les séances de travail `STEP`, pas dans `JOB`.

7. *La balise et le texte prêt à livrer* (`vocab.affect.parse_tag`).
   - **Les variantes réelles sont reconnues** : crochets doublés, parenthèses, accolades, `=`/`,`, `60%`, échelles sur 0–10 et 0–100, point final, balise non fermée, « Émotion : happy (0.6) », noms français et synonymes (`emotion_named`), intensifs (`very_happy`). La **dernière** balise gagne.
   - **Une forme abrégée au milieu d'une phrase**, en casse de titre et sans intensité (« J'ai lancé [Curious] »), reste du texte ; un lien markdown aussi.
   - **La prosodie suit la grammaire exacte du frontend** (`[PAUSE:ms]` entier, `[SIGH]`, `[LAUGH]`, `[BREATH]`), synonymes compris. Les autres jetons entre crochets en capitales sont retirés.
   - **Les didascalies** de rire, de soupir et de souffle deviennent leur jeton de voix ; les autres gestes sont retirés. Une emphase (`*vraiment*`) et une vraie parenthèse restent.
   - **« Mika : », les guillemets englobants et le raisonnement** (`<thinking>…`) sont ôtés.
   - **`[SILENCE]` n'est jamais abîmé** : il est seulement débarrassé de ses débris de markdown.

**Faits (sémantique finale, pour qui les lit).**
- `REGARD` ∈ [−1, 1] : la part de l'ancre (depuis le repos moyen) + 0,3 × `BOND`. Quatorze soirées chaleureuses donnent environ 0,35. Après quinze colères, une amie garde un regard positif : environ +0,02 après trois semaines de soirées, environ +0,1 après un mois.
- `WARMTH` = max(0, `REGARD`).
- `HOSTILITY` ∈ [0, 1] : le déplaisir dominant de l'ancre × (1 − 0,6 × `BOND`), avec le plancher de méfiance. Douze insultes d'une inconnue donnent environ 0,44, encore 0,41 le lendemain et ≥ 0,1 pendant 14 jours. Quinze colères donnent environ 0,43 envers une inconnue, mais environ 0,11 envers une amie de trois semaines (0,06 après un mois). Un seuil de rétrogradation d'une amie à 0,35 (lot social) laisse une marge.
- `BOND` ∈ [0, 1] (nouveau) : l'attachement.
- `MOOD` : `home` est le repos jumeau, `overflow` l'émotion du moment seule. Nouveaux champs : `fond`, `cause`, `cause_person`.
- `STANCE` : `declared` est la balise en décroissance. Nouveaux champs : `reference`, `regard`, `hostility`, `bond`, `declared_at`, `declared_reply`, `lasting`.
- `FACE` : la balise de la dernière réplique tant qu'elle dure.

**Conséquences.**
- La tranche passe en version 2 et se reconstruit par rejeu.
- `declared_window_us` est retiré : les anciens `kernel.params_changed` qui le portent se rejouent.
- Les nouveaux paramètres ont tous un `Knob` borné. Ils sont regroupés sous « Le fond d'une journée » et « L'histoire d'une relation ».
- Les bandes du simulateur restent vertes sans recalibrage : S01 (résidus 0,86 et 0,01), S02 (hostilité du troll 0,43 au lieu de 0,31), S03 (débordement 0,38).
- Reste hors de ce lot :
  - donner au modèle l'échelle de la balise (0,2 / 0,5 / 0,8), dans la consigne de style d'`expression` ;
  - poser au réveil les évaluations des rêves et de la digestion (PSY-7) ;
  - relever le seuil de rétrogradation d'une amie (lot social).
