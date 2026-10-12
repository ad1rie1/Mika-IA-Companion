# 0103 — La constellation : sa mémoire en une boule de points, et ce qui la parcourt

**Contexte.** La console montre sa mémoire en tables. On y lit un souvenir, sa provenance, pourquoi une parole l'a
cité ; on n'y voit pas sa mémoire d'un coup d'œil, ni ce qui la traverse quand elle parle, consolide ou dort. La
propriétaire a demandé une vue « futuriste » : tous ses souvenirs comme des points d'une boule, et les agents qui les
parcourent, en direct.

**Décision.**
- **Une page de la console, réservée aux opérateurs** : `/inspecteur/constellation` (menu « Elle » › Constellation).
  Plein écran, WebGL2 écrit à la main — aucune bibliothèque, la politique de sécurité de la console ne sert que ses
  propres scripts. Elle montre tout, secrets compris, comme le reste de la console : un compte qui n'est pas
  opérateur est renvoyé à la connexion, ses lectures reçoivent 401.
- **Chaque point est un élément de l'index des vecteurs** (souvenir, croyance, promesse, moment, échange). Sa
  **direction** vient de ses voisins de sens (`adapters/vectors/layout.py`) : les dix plus proches dans l'espace des
  plongements, en pleine dimension, le tirent vers eux sur la sphère ; quelques points tirés au sort le repoussent
  (un plongement de voisinage à la UMAP, posé sur la sphère, numpy seul, graine fixe). Mesuré sur 400 phrases réelles
  (MiniLM multilingue) : 73 % des dix voisins de sens restent parmi les dix voisins sur la sphère (21 % pour une
  ACP, 3 % au hasard). Les **filaments** sont ces voisins-là, pas ceux de la projection.
- **La profondeur se choisit à l'écran** : le temps (l'ancien au cœur, le récent en surface), la vivacité
  (importance, rappels récents), ou la surface. La couleur : la sorte, la personne, l'émotion, la sensibilité, l'âge.
- **Une carte qui ne saute pas.** Recalculée quand l'index a gagné ou perdu des points, elle part de la précédente :
  ce qui était là bouge d'un ou deux degrés, ce qui arrive se pose parmi les siens. Au-delà de 8 000 vecteurs, les
  voisins se cherchent dans 48 axes principaux ; au-delà de 50 000, seuls les plus récents sont sur la carte, et la
  page le dit. Le calcul part dans un fil (2,5 s pour 10 000 points, ~20 s pour 50 000).
- **Rien ne bouge pour faire joli : chaque trajet est un événement du journal.** Le noyau publie chaque lot commité
  (`Mind.subscribe`) ; la constellation y lit :
  - une **parole** et sa provenance (`memory:…`, `chunk:…`, `veiled:…`) : ce que son prompt lui montrait vraiment.
    L'agent est la sorte d'épisode (réponse, initiative, murmure, travail). Pour une réponse, le **sondage** — les
    voisins les plus proches du message auquel elle répondait — est recalculé par la même recherche que l'index : il
    dit ce qui *ressemblait*, la comète ce qui lui est *revenu*. La page l'écrit en toutes lettres ;
  - un **élément qui naît** (la consolidation, la genèse), plongé et posé près de ses voisins sans recalculer la
    carte ; un **renfort** ;
  - **la nuit** : souvenirs fondus, croyances réunies ou confrontées, la relecture ;
  - un **rêve**, son **récit**, son **journal** : leurs sources, dans l'ordre ;
  - un **oubli** : la carte se recalcule.
- **Recadrer sur quelque chose** (`/cherche?q=`, la barre de l'en-tête, raccourci `/`) : d'abord ce dont le texte
  **contient** ces mots — replié, casse et accents ignorés, `%` et `_` pris pour eux-mêmes, comme la console —, puis
  ce qui leur **ressemble**, noté comme sa recherche délibérée (similarité des vecteurs, plus un bonus pour les mots
  du sujet) : tout ce qui dépasse 0,4, sans écart au meilleur (le choix de la propriétaire, `SEARCH_FLOOR`). Sans
  seuil, les 24 plus proches remontaient aussi du hors-sujet ; la règle du rappel en conversation (0,45 et un écart
  au meilleur de 0,5) en montrait trop peu. Sur des requêtes très courtes, le modèle reste bruité (mesuré :
  « musique » → « Il apprend Rust le soir » à 0,45, devant le piano à 0,41). Seulement ce qui est sur la carte ; la
  page la recalcule d'abord si l'index a gagné des éléments. Les
  résultats restent allumés, le reste s'efface, la caméra vole vers leur direction ; un nom de personne propose de ne
  montrer que ses points. Les marques (résultats, point ouvert, survol) sont une couche à part, dessinée après le halo,
  en pixels : des souvenirs presque identiques reçoivent **un seul anneau**, centré sur leur groupe, au lieu d'une
  tache de dix anneaux qui s'additionnent.
- **Les textes ne partent qu'à la demande** : la carte porte des clés, des directions, de quoi colorer ; un point
  survolé ou ouvert lit son texte (`/point/<n>`), écrit côté page par `textContent`. Seul l'extrait du message auquel
  elle répondait (90 caractères) accompagne un rappel.
- **Elle ne coûte que si quelqu'un regarde** : sans lecture du flux depuis 30 s, les événements ne sont même pas
  triés ; le flux est un anneau de 400 éléments en mémoire, lu toutes les secondes par la page (`/flux?apres=`),
  jamais une connexion tenue ouverte. « Rejouer » (`/rejeu`) traduit les dernières paroles qui se sont souvenues de
  quelque chose, le dernier rêve et le dernier récit, comme en direct.

**Conséquences.**
- Une vue de plus sur sa mémoire, qui la rend lisible d'un coup d'œil (les grappes, les doublons, ce qui ne revient
  jamais) et qui montre le rappel au moment où il se fait.
- La composition (`app/constellation.py`) lit la porte de la console (`memory_ledger`, `memory_chunks`) et l'index
  des vecteurs ; ni le runtime ni l'inspecteur ne nomment une faculté. L'index gagne `dump()`, qui rend tout l'index
  d'un modèle rangé par clé.
- Tests : `tests/unit/test_constellation_layout.py` (voisins gardés contre une carte au hasard, sphère couverte,
  déterminisme, stabilité contre un recalcul à froid, filaments exacts, placement d'un nouveau vecteur) et
  `tests/protocol/test_constellation.py` (opérateurs seulement, la carte sans textes, rien sans lecteur, une naissance
  dans le flux, une réponse et sa provenance, le rejeu, la recherche par les mots puis par le sens). Vérifiés non vides
  en cassant la porte « personne ne regarde », l'ordre de la provenance et l'échappement de `%`.
