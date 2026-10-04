"""GestionSystème — interface d'administration et de pilotage de l'IA.

Remplace l'ancienne application ``dashboard``. Deux différences de fond :

1. **Rendu serveur.** Les tableaux, les formulaires et les fiches sont
   produits par des gabarits Django. L'ancienne interface assemblait tout
   côté navigateur par concaténation de chaînes (125 ``innerHTML``, 260
   appels manuels d'échappement) : la protection contre l'injection
   reposait sur le fait de ne jamais en oublier un, sans outil pour le
   vérifier. Ici l'échappement est celui du moteur de gabarits, actif par
   défaut, et ``sanitize.py`` n'a plus à rattraper le rendu.

2. **Les modules ont un espace, pas une page.** Un module déclare des
   ``ModulePanel`` et reçoit une section entière — ses vues, sa
   configuration, son état et son journal au même endroit — au lieu
   d'entrées éparpillées dans un menu global.
"""
