# 0015 — L'arbitre tire contre une borne locale

**Contexte.** L'amincissement tirait les occurrences contre la borne globale `λ_max` (une toutes les dix secondes dès qu'une personne était présente), puis rejetait presque tout. Chaque réveil recalcule les preuves ; avec la retenue (qui lit la guérison des ancres), deux jours simulés prenaient 14 s.

**Décision.** La borne est le double de l'intensité **actuelle** ; une occurrence plus lointaine que la réévaluation (5 min) devient une simple réévaluation. L'intensité ne change qu'avec un événement (réévaluation immédiate) ou avec le temps (réévaluation périodique) ; entre deux, la marge couvre sa dérive. Le tirage est indexé sur un compteur (pas sur l'instant : il doit rester indépendant de la cadence des réveils à la microseconde près). La guérison d'une ancre sur plusieurs jours est calculée en forme close : une journée type composée une fois, élevée à la puissance (écart à l'intégration exacte : 4e-16).

**Conséquences.** Deux jours simulés : 0,3 s. Le test M0 d'indépendance à la cadence (mêmes instants graine par graine, loi exponentielle) reste vert.
