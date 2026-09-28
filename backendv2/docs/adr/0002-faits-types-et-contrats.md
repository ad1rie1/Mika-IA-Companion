# 0002 — Des faits typés et des contrats par propriétaire

**Contexte.** En v1, 13 paquets sur 15 formaient un seul cycle d'imports ; l'intégration passait par le prompt et par des appels directs.

**Décision.** Les facultés ne s'importent pas. Elles lisent des faits typés (un fournisseur par clé, graphe acyclique, lectures déclarées) et réduisent les événements publics déclarés dans `contracts/<propriétaire>.py`. Les événements sont privés par défaut.

**Conséquences.** Couplage explicite et vérifié ; un seul fichier par propriétaire dit ce qu'il partage. Risque : un vocabulaire qui regrossit — d'où les règles d'admission (au moins deux consommateurs, petites valeurs).
