# 0098 — Seule et désœuvrée, elle a une vie : s'occuper, un souvenir qui revient

**Contexte.** Éveillée et seule, il ne se passait presque rien en elle. Ses mains ne servaient qu'en conversation (les
outils `go_to`, `interact`) ou à son bureau quand elle travaillait ; jamais elle ne prenait d'elle-même un livre, ne
dessinait, ne regardait dehors. Aucun souvenir ne lui revenait de lui-même : ses rêves seuls puisaient dans sa
mémoire, la nuit ; la date anniversaire d'un moment ne lui disait rien (elle ne servait qu'à un mot doux à une proche,
le jour d'un deuil). L'ennui et la solitude se ressentaient (`needs.felt`), et c'était tout. Et quand une occupation
venait, deux minutes à regarder dehors effaçaient deux heures d'ennui, solitude comprise.

**Décision.** Deux tendances bornées, sans appel au modèle.

1. *S'occuper* (`world._occupy_herself`). Le vide ressenti la fait s'occuper de ce qui nourrit ce qui lui manque le
   plus — dessiner quand c'est l'envie de dire, feuilleter un livre ou regarder dehors quand c'est la curiosité (ce
   que chaque objet nourrit est déclaré par le monde, `nourishes`), jamais deux fois de suite la même chose. Au plus
   `world.occupy_per_day` (3) fois par jour, espacées de `occupy_spacing_min` (2 h) ; rien en dormant, allongée, en
   chemin, déjà occupée, ni juste après avoir parlé à quelqu'un. Comme son bureau quand elle travaille, l'intention
   naît de l'événement (un ressenti déjà là, rendu visible).
2. *Ce que s'occuper fait au vide* (`needs`). Le vide qu'elle avait avant s'y mettre s'efface **au prorata** de ce que
   l'occupation a comblé (`occupied_full_us`) : deux minutes à regarder dehors ne valent pas deux heures de répit,
   une heure à dessiner, si. Et s'occuper tient l'ennui à distance, **pas la solitude** : celle-ci court depuis le
   dernier contact (`lonely_since` : un message qu'on lui adresse, sa parole à quelqu'un, son réveil, une séance de
   travail qui l'absorbe — PSY-18).
3. *Un souvenir qui revient* (`attention.watch`, origine `reminiscence`). Après un moment où rien ne se passe
   (`reminisce_idle_us`), au plus `reminisce_per_day` (2) par jour, espacés : un souvenir un peu ancien
   (`reminisce_min_age_us`, une semaine) lui revient — d'abord celui dont c'est la date anniversaire (« Il y a un an
   jour pour jour : … »), puis ce que lui rappelle ce qu'elle a entre les mains (« Occupée à dessiner, un souvenir te
   revient : … »), sinon l'un de ceux qui comptent (tiré au poids de leur importance). Jamais un qui vient de revenir.
   Ses mots à elle, son émotion d'alors (jugée à la relecture ; aucune émotion inventée : sans émotion notée, une
   pensée) ; sa filiation le suit — il ne se redit que devant qui ses sources le permettent. Il se ressent (cause
   `reminiscence` : « Ça vient d'un souvenir qui t'est revenu ») et peut se raconter à qui il concerne (`needs`,
   `WITH_THEM`) ; il n'est jamais à lui seul une raison d'écrire (`FELT_ONLY`), ni d'ouvrir une exploration.

**Conséquences.** Origine `attention.REMINISCENCE` ; réglages `world.occupy_per_day`, `occupy_spacing_min`,
`attention.reminisce_*` (groupe « Les souvenirs qui reviennent ») ; `WorldState.occupied`, `AttentionState.reminisced`,
`NeedsState.lonely_since`, `Occupation.void_from` / `noted` ; `world` v7 (attention v14 et needs v7 complétés). Le
scénario S06 (« la journée vide ») vérifie qu'elle s'occupe d'elle-même, quelques fois seulement, et que la journée
se ressent quand même. Cibles : `tests/unit/test_alone.py` ; 16 mutations, toutes rouges.

**Ce qui n'est pas fait.** Le choix d'une occupation suit ce qui lui manque, pas encore ses goûts (une persona qui
adore dessiner ne dessine pas davantage). Un souvenir ne revient pas par un lieu de sa chambre, une odeur, un mot lu :
seulement par sa date, ce qu'elle fait, ou sans raison. Rien de tout cela ne passe par le modèle : ni un monologue,
ni un choix délibéré de sa part.
