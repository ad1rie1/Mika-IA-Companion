# 0003 — L'initiative par preuves cumulées et déclenchement à taux

**Contexte.** En v1, un score linéaire à onze facteurs, évalué toutes les 30 s, dont les plafonds devaient sommer exactement au seuil ; le comportement dépendait de la cadence.

**Décision.** Des preuves en log-odds, cumulées par (type, cible), modulées par décalages additifs ou vetos ; un processus de Poisson d'intensité `λ_max · σ(score)` tiré par amincissement ; plages déclarées et atteignabilité vérifiée au démarrage.

**Conséquences.** Les raisons faibles s'additionnent comme en v1 ; le comportement ne dépend plus de la cadence (vérifié : mêmes instants graine par graine) ; la table des lignes explique chaque décision.
