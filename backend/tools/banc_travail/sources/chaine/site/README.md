# Le site de Mirette

Un site statique : quatre pages et un blog, servis tels quels depuis la branche `main`.

- `index.html` : l'accueil ;
- `fonctions.html` : ce que fait Mirette ;
- `tarifs.html` : les prix ;
- `blog/` : un article par fichier, et `blog/index.html` qui les liste (le plus récent en haut).

Un article : un fichier `blog/<titre-court>.html`, sur le modèle de `blog/bienvenue.html`, puis sa ligne dans
`blog/index.html`. Pas de générateur, pas de dépendance : on écrit le HTML à la main.
